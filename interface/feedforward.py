
"""
interface/feedforward.py -- Stage 4 feedforward.

Shows the caller what is about to happen (or just happened) in plain,
templated text, and decides whether the request must pass a hard confirm gate
because it is expensive. No AI: string templates over the Stage 3 RoutingPlan.

Where it sits (ARCHITECTURE.md Stage 4): after Stage 3 planning, before
execution. The plan is pure (no model call), so rendering it costs nothing.

Decisions (kept inside the frozen Stage 4 spec; no structural change):

1. Two moments, one text source.
   * Gated request (REQUIRE_HUMAN or high cost): the route preview is placed in
     the needs-confirmation response, so the human confirms informed and
     BEFORE anything runs. This is the real feedforward.
   * Ungated request: a single-call API cannot show text before generation, so
     the outcome ("Answered by ...") is attached to the response. It is logged
     as attached-to-response, not as shown-before. A pre-generation preview
     mode is tracked as an open item for the user study.

2. The text never exposes classifier internals (category, confidence, floor,
   keyword hits). Stage 3 #6 names the router/classifier as attack surface; a
   caller who sees how requests are scored can tune input to be misrouted. The
   audit log keeps the full rationale; the caller sees route, model, cost.

3. The hard gate is cost-based. "High-stakes" is already enforced by the
   policy-defined REQUIRE_HUMAN checkpoint (interface/human_checkpoint.py).
   The classifier's HIGH_STAKES category is deliberately NOT a confirm gate: it
   includes self-harm keywords, and putting a confirmation wall in front of
   someone who may be in distress would do more harm than good.

4. Failure behavior (Stage 4 #7):
   * Rendering the text fails -> fail OPEN: the request proceeds without the
     text and the audit record says so. REQUIRE_HUMAN is unaffected because it
     is enforced by the checkpoint, not by this module.
   * Evaluating the cost gate fails -> fail CLOSED: we cannot show the request
     is not expensive, so confirmation is required.

5. Gating uses the upper bound of the energy estimate (wh_high) summed over
   every rung that might run, so uncertainty cannot push a request under the
   limit. The limits below are PLACEHOLDERS (see OPEN_ENDS); with the current
   catalog they trip only for the largest model or very large inputs.
"""
from __future__ import annotations

import logging
import math
import numbers
from dataclasses import dataclass
from typing import Optional

from policy.schemas import MethodTier
from triage.decision import RoutingPlan

log = logging.getLogger(__name__)

HIGH_COST_WH = 3.0       # PLACEHOLDER, uncalibrated
HIGH_COST_USD = 0.05     # PLACEHOLDER, uncalibrated

# Folded into the confirmation token's bound rule set when the gate applies, so
# a plain token can never acknowledge the cost gate.
GATE_COST_ID = "FF-HIGH-COST"

_LABELS = {
    MethodTier.CACHE: "saved answer for an exact repeat",
    MethodTier.DETERMINISTIC: "rule-based solver (no AI)",
    MethodTier.SMALL_CLASSIFIER: "small classifier",
    MethodTier.RAG_SMALL_MODEL: "small model with reference material",
    MethodTier.LLM_LOW_REASONING: "language model",
    MethodTier.LLM_HIGH_REASONING: "language model (high reasoning)",
}


@dataclass(frozen=True)
class Gate:
    required: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteCost:
    wh: float          # central estimate, summed over every rung that may run
    wh_high: float     # upper bound, used for gating
    usd: float
    latency_ms: float


def _label(tier: MethodTier, model_name: Optional[str]) -> str:
    base = _LABELS[tier]
    return f"{base} ({model_name})" if model_name else base


def worst_case(plan: RoutingPlan) -> RouteCost:
    """Cost if every attempted rung runs and only the last one answers."""
    steps = [s for s in plan.steps if s.attempt]
    return RouteCost(
        wh=sum(s.estimate.tier_estimate.est_energy_wh for s in steps),
        wh_high=sum(s.estimate.wh_high for s in steps),
        usd=sum(s.estimate.tier_estimate.est_dollar_cost for s in steps),
        latency_ms=sum(s.estimate.tier_estimate.est_latency_ms for s in steps),
    )


def _check_limit(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {value!r}")
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")
    return v


def evaluate_gate(plan: RoutingPlan, high_cost_wh: float = HIGH_COST_WH,
                  high_cost_usd: float = HIGH_COST_USD) -> Gate:
    """Hard confirm gate for expensive requests. Fails CLOSED on any error."""
    wh_limit = _check_limit("high_cost_wh", high_cost_wh)      # config errors are loud
    usd_limit = _check_limit("high_cost_usd", high_cost_usd)
    try:
        cost = worst_case(plan)
        reasons = []
        if cost.wh_high >= wh_limit:
            reasons.append(f"worst-case estimated energy of {cost.wh_high:.2f} Wh "
                           f"reaches the {wh_limit:g} Wh limit")
        if cost.usd >= usd_limit:
            reasons.append(f"worst-case estimated cost of ${cost.usd:.4f} "
                           f"reaches the ${usd_limit:g} limit")
        return Gate(bool(reasons), tuple(reasons))
    except Exception:
        log.exception("cost gate evaluation failed; failing closed")
        return Gate(True, ("the cost of this request could not be estimated",))


def preview_text(plan: RoutingPlan) -> str:
    steps = [s for s in plan.steps if s.attempt]
    path = " -> ".join(_label(s.tier, s.model_name) for s in steps)
    c = worst_case(plan)
    return (f"Planned route, cheapest first: {path}. A later step runs only if the "
            f"earlier ones cannot answer. Worst-case estimate: about {c.wh:.2f} Wh of "
            f"energy, ${c.usd:.4f} and {c.latency_ms / 1000:.1f} s "
            f"(rough estimates, not measurements).")


def outcome_text(plan: RoutingPlan, tier_used: MethodTier) -> str:
    step = plan.step_for(tier_used)
    if step is None or not step.attempt:
        raise ValueError(f"{tier_used!r} was not an attempted tier in this plan")
    est = step.estimate.tier_estimate
    return (f"Answered by: {_label(step.tier, step.model_name)}. Estimated cost of this "
            f"step: about {est.est_energy_wh:.4f} Wh and ${est.est_dollar_cost:.4f} "
            f"(rough estimates, not measurements).")


def safe_preview(plan: RoutingPlan) -> Optional[str]:
    """Fail OPEN: a rendering error yields None, never an exception."""
    try:
        return preview_text(plan)
    except Exception:
        log.exception("feedforward preview failed; proceeding without it")
        return None


def safe_outcome(plan: RoutingPlan, tier_used: MethodTier) -> Optional[str]:
    try:
        return outcome_text(plan, tier_used)
    except Exception:
        log.exception("feedforward outcome failed; proceeding without it")
        return None
