
"""
Stage 3 -- Necessity & Cost Router (Sprint 4).

Turns a normalized request into a RoutingPlan: the full cheapest-first ladder
(cache -> deterministic -> small classifier -> RAG -> LLM), which rungs are
worth attempting, why each skipped rung was skipped, and a cost estimate for
every rung. ARCHITECTURE.md Stage 3 #4 and #9 ("a tier may only be skipped
with a logged, documented reason"; "which cheaper tiers were tried and
rejected and why") are satisfied by the TierStep.reason strings.

This module PLANS; it does not execute. Stage 5 (api/main.py) walks
plan.attempt_order, and a tier that returns None escalates to the next
attempted tier (Stage 3 #10). Once a tier answers, plan.decision_for(tier)
builds the RoutingDecision for the audit log. policy/schemas.py is not
touched, so no Change Proposal is needed.

Design decisions (see the chat/OPEN_ENDS entries for the reasoning):

1. Confidence is a FLOOR THAT CAN ONLY ESCALATE. Category membership
   (CHEAP_TIER_ELIGIBLE) is the primary gate; a request that is in an
   eligible category but classified below `min_confidence` is denied the
   small-classifier/RAG rungs. Higher confidence never admits a category
   that is not already eligible. This mirrors the "may only tighten" rule of
   Stage 2 and Stage 3 #7 (uncertain classification -> escalate up).
   DEFAULT_MIN_CONFIDENCE (0.4) matches classifier.py today, where the
   confidence formula bottoms out at 0.55, so the floor is currently inert:
   the mechanism is live and tested, the value is uncalibrated (golden set).

2. The deterministic rung is SELF-GATING (strict regex / static table; it
   returns None when unsure), so it is attempted regardless of category
   except HIGH_STAKES. Gating it on the keyword classifier would be a
   regression: "2 + 2" classifies as UNKNOWN and must still reach it.

3. Classifier failure (exception or wrong return type) is treated as UNKNOWN
   with confidence 0.0 and the LLM capability floor is raised to the maximum
   (Stage 3 #7), rather than silently falling back to the cheapest model.

4. LLM_HIGH_REASONING is deliberately not on this ladder. Reaching it is an
   escalation event owned by escalation/repair_router.py (Sprint 5).

Configuration errors (bad catalog, non-finite floor) propagate as exceptions
on purpose: they are programmer errors, not request-time failures.
"""
from __future__ import annotations

import logging
import math
import numbers
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from cost.estimator import CostEstimate, estimate_tier
from cost.model_registry import ModelInfo
from policy.schemas import (
    MethodTier,
    PolicyFlag,
    RequestClassification,
    RequestType,
    RoutingDecision,
)
from tiers.model_selector import select_model
from triage.classifier import classify, is_cheap_tier_eligible
from triage.taxonomy import CHEAP_TIER_ELIGIBLE

log = logging.getLogger(__name__)

# Matches classifier.is_cheap_tier_eligible's default. Uncalibrated (OI-018 style
# follow-up: calibrate against the golden set).
DEFAULT_MIN_CONFIDENCE = 0.4

# Above every catalog capability_score, so select_model takes its
# "nobody qualifies -> highest-capability model" escalation path.
CONSERVATIVE_FLOOR = 1.0

# PLACEHOLDER capability floors (catalog capability scores are themselves
# placeholders, OI-005). Only HIGH_STAKES is raised for now.
MIN_CAPABILITY_BY_CATEGORY: dict[RequestType, float] = {
    RequestType.HIGH_STAKES: 0.7,
}


@dataclass(frozen=True)
class TierStep:
    """One rung of the ladder, attempted or skipped, with its reason and cost."""
    tier: MethodTier
    attempt: bool
    reason: str
    estimate: CostEstimate
    model_name: Optional[str] = None


@dataclass(frozen=True)
class RoutingPlan:
    classification: RequestClassification
    min_confidence: float
    classifier_failed: bool
    steps: tuple[TierStep, ...]

    @property
    def attempt_order(self) -> tuple[MethodTier, ...]:
        """Tiers Stage 5 should try, cheapest first. The LLM rung is always last."""
        return tuple(s.tier for s in self.steps if s.attempt)

    @property
    def rationale(self) -> str:
        c = self.classification
        if self.classifier_failed:
            head = "classifier failed; treated as UNKNOWN and routed conservatively"
        else:
            head = (f"classified {c.category.value} (confidence {c.confidence:.2f}, "
                    f"floor {self.min_confidence:.2f})")
        parts = [f"{s.tier.value}: {'try' if s.attempt else 'skip'} - {s.reason}"
                 for s in self.steps]
        return head + ". " + "; ".join(parts) + "."

    def step_for(self, tier: MethodTier) -> Optional[TierStep]:
        return next((s for s in self.steps if s.tier == tier), None)

    def decision_for(self, tier_used: MethodTier,
                     policy_flags: Optional[Sequence[PolicyFlag]] = None) -> RoutingDecision:
        """Build the audit-ready RoutingDecision for the tier that actually answered."""
        step = self.step_for(tier_used)
        if step is None or not step.attempt:
            raise ValueError(f"{tier_used!r} was not an attempted tier in this plan; "
                             f"attempted: {[t.value for t in self.attempt_order]}")
        return RoutingDecision(
            selected_tier=tier_used,
            selected_model=step.model_name,
            rationale=f"{tier_used.value} answered. {self.rationale}",
            cost_estimate=step.estimate.tier_estimate,
            policy_flags=list(policy_flags or []),
        )


def _validate_min_confidence(value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"min_confidence must be a real number, got {value!r}")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"min_confidence must be finite, got {value!r}")
    return v


def _why_not_cheap(cls: RequestClassification, failed: bool, floor: float) -> str:
    if failed:
        return "classifier failed; escalate rather than guess"
    if cls.category not in CHEAP_TIER_ELIGIBLE:
        return f"category {cls.category.value} is not cheap-tier eligible"
    return f"confidence {cls.confidence:.2f} is below the floor {floor:.2f}"


def plan_request(
    request_text: str,
    *,
    classifier: Callable[[str], RequestClassification] = classify,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    objective: str = "energy",
    catalog: Optional[Sequence[ModelInfo]] = None,
) -> RoutingPlan:
    """Plan the cheapest-first ladder for one normalized request.

    Call this only after Stages 0-2 have passed (Stage 3 #5). `classifier` is
    injectable so tests and the Sprint 6 attack suites can drive it directly.
    """
    floor = _validate_min_confidence(min_confidence)

    failed = False
    try:
        cls = classifier(request_text)
        if not isinstance(cls, RequestClassification):
            raise TypeError(f"classifier returned {type(cls).__name__}, not RequestClassification")
    except Exception:
        log.exception("classifier failed; routing conservatively")
        cls = RequestClassification(category=RequestType.UNKNOWN, confidence=0.0,
                                    raw_text=request_text if isinstance(request_text, str) else "")
        failed = True

    cat = cls.category
    cheap_ok = (not failed) and is_cheap_tier_eligible(cls, floor)
    skip_reason = "" if cheap_ok else _why_not_cheap(cls, failed, floor)

    steps: list[TierStep] = []

    steps.append(TierStep(
        MethodTier.CACHE, True,
        "exact-match cache on normalized text; never bypasses Stage 0/1",
        estimate_tier(MethodTier.CACHE, request_text, None, cat)))

    det_attempt = cat is not RequestType.HIGH_STAKES
    steps.append(TierStep(
        MethodTier.DETERMINISTIC, det_attempt,
        "self-gating solver, returns None when unsure" if det_attempt
        else "high-stakes request is never answered by a rule-based shortcut",
        estimate_tier(MethodTier.DETERMINISTIC, request_text, None, cat)))

    steps.append(TierStep(
        MethodTier.SMALL_CLASSIFIER, cheap_ok,
        "category cheap-tier eligible and confidence at or above the floor" if cheap_ok
        else skip_reason,
        estimate_tier(MethodTier.SMALL_CLASSIFIER, request_text, None, cat)))

    rag = select_model(MethodTier.RAG_SMALL_MODEL, request_text, request_type=cat,
                       objective=objective, catalog=catalog)
    steps.append(TierStep(
        MethodTier.RAG_SMALL_MODEL, cheap_ok,
        ("category cheap-tier eligible and confidence at or above the floor; "
         + rag.rationale) if cheap_ok else skip_reason,
        rag.estimate, rag.model.name))

    min_capability = CONSERVATIVE_FLOOR if failed else MIN_CAPABILITY_BY_CATEGORY.get(cat, 0.0)
    llm = select_model(MethodTier.LLM_LOW_REASONING, request_text, request_type=cat,
                       min_capability=min_capability, objective=objective, catalog=catalog)
    steps.append(TierStep(
        MethodTier.LLM_LOW_REASONING, True,
        "last resort on the ladder, always attempted; " + llm.rationale,
        llm.estimate, llm.model.name))

    return RoutingPlan(classification=cls, min_confidence=floor,
                       classifier_failed=failed, steps=tuple(steps))
