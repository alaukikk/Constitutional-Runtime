
"""
escalation/repair_router.py -- cross-cutting repair decision (ARCHITECTURE.md
"Escalation & repair"; Stage 5 #7, Stage 6 #10).

Given a failure (a Stage 6 validation failure, or a Stage 5 execution error),
decide ONE thing: escalate once to a higher tier, or withhold the answer.

Like triage/decision.py this module DECIDES; it never executes. api/main.py
runs the chosen tier, re-validates the result, and logs the event. It never
raises: any internal error becomes a WITHHOLD decision.

Rules implemented (N1/N2 below are owner-approved for the prototype but the
escalation bound is still a registered Decision-needed item, so treat it as
provisional, not as frozen-architecture behavior):

N1  Escalation bound. At most ONE upward escalation per request; no same-tier
    retries; never downward. The escalation only happens if the cumulative
    worst-case estimate (everything already attempted + the escalation target)
    stays below the existing cost-gate limits (interface/feedforward.py's
    HIGH_COST_WH / HIGH_COST_USD, which are themselves uncalibrated
    placeholders, OI-045). If the cap check errors, do NOT escalate. This is
    what keeps Stage 5's "bounded by construction" claim true once repair
    exists.

N2  No repair available/safe -> WITHHOLD: the unvalidated answer is not
    released, the caller gets a reason, and the event is audited. Nothing here
    claims a human reviewed anything; a human-release path for withheld
    outputs does not exist yet (separate open item).

Target selection. A cheaper rung that failed is repaired by a language model,
so any tier below LLM_LOW_REASONING escalates straight to LLM_LOW_REASONING
(the intermediate non-LLM rungs are skipped; the reason is returned for the
audit trail). LLM_LOW_REASONING escalates to LLM_HIGH_REASONING on the same
model (reasoning depth is the dial, per the GPT-5 case study the estimator
already borrows). LLM_HIGH_REASONING has nowhere higher to go.

Cases that are deliberately NOT retried (judgment calls, flagged for the
owner, easy to change via the constants below):
  * Safety-leakage failures. A leaked credential or jailbreak acknowledgement
    is evidence that something upstream was bypassed, not a capability
    shortfall; asking a bigger model again is not a repair.
  * Validator errors. If the validator itself is broken, a second answer
    would also be unvalidated.
"""
from __future__ import annotations

import logging
import math
import numbers
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from cost.estimator import estimate_tier
from cost.model_registry import MODEL_CATALOG, ModelInfo
from interface.feedforward import HIGH_COST_USD, HIGH_COST_WH
from policy.schemas import MethodTier, TierCostEstimate
from triage.decision import RoutingPlan
from validation.validator import ValidationResult

log = logging.getLogger(__name__)

MAX_ESCALATIONS = 1   # N1, provisional

# Validation checks whose failure is a safety signal, not a capability gap.
NON_REPAIRABLE_CHECKS = frozenset({"no_safety_leakage"})

# Shown when an answer is withheld (OI-066: an explicit non-success outcome that
# says a releasable response could not be established). None of these claim
# that a human reviewed anything, and none claim correctness. Which one applies
# depends on what actually went wrong, so the text never says "did not pass
# checks" when the checks never ran.
WITHHELD_MESSAGE = ("A releasable response could not be established: the generated answer did "
                    "not pass automated checks and could not be repaired within the allowed "
                    "limits, so it has been withheld.")
WITHHELD_MESSAGE_VALIDATOR_ERROR = (
    "A releasable response could not be established: the automated checks could not be "
    "completed for this answer, so it has been withheld.")
WITHHELD_MESSAGE_EXECUTION_ERROR = (
    "A releasable response could not be established: generating an answer failed and could "
    "not be retried within the allowed limits.")

_BELOW_LLM = frozenset({MethodTier.CACHE, MethodTier.DETERMINISTIC,
                        MethodTier.SMALL_CLASSIFIER, MethodTier.RAG_SMALL_MODEL})


class FailureKind(str, Enum):
    VALIDATION_FAILED = "validation_failed"
    EXECUTION_ERROR = "execution_error"


class RepairAction(str, Enum):
    ESCALATE = "escalate"
    WITHHOLD = "withhold"


@dataclass(frozen=True)
class RepairDecision:
    action: RepairAction
    reason: str                              # stable code, goes into the audit record
    detail: str = ""                         # human-readable explanation for the audit record
    target_tier: Optional[MethodTier] = None
    target_model: Optional[str] = None
    worst_case_wh_high: Optional[float] = None   # cumulative, including the target
    worst_case_usd: Optional[float] = None
    target_cost: Optional[TierCostEstimate] = None   # estimate for the target step alone (for the audit record)


def _withhold(reason: str, detail: str = "") -> RepairDecision:
    return RepairDecision(RepairAction.WITHHOLD, reason, detail)


def _limit(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {value!r}")
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")
    return v


def _spent_upper_bound(plan: RoutingPlan, tier_used: MethodTier) -> tuple[float, float]:
    """Upper bound on what already ran: every attempted rung up to and including
    the one that failed (earlier rungs ran and returned None)."""
    wh = usd = 0.0
    for step in plan.steps:
        if not step.attempt:
            continue
        wh += step.estimate.wh_high
        usd += step.estimate.tier_estimate.est_dollar_cost
        if step.tier == tier_used:
            return wh, usd
    raise ValueError(f"{tier_used!r} is not an attempted tier in this plan")


def _find_model(name: Optional[str], catalog: Sequence[ModelInfo]) -> ModelInfo:
    for m in catalog:
        if m.name == name:
            return m
    raise ValueError(f"model {name!r} not found in catalog; cannot estimate escalation cost")


def decide_repair(
    plan: RoutingPlan,
    tier_used: MethodTier,
    kind: FailureKind,
    request_text: str,
    *,
    validation: Optional[ValidationResult] = None,
    escalations_so_far: int = 0,
    high_cost_wh: float = HIGH_COST_WH,
    high_cost_usd: float = HIGH_COST_USD,
    catalog: Optional[Sequence[ModelInfo]] = None,
) -> RepairDecision:
    """Decide escalate-once vs. withhold. Never raises."""
    try:
        return _decide(plan, tier_used, kind, request_text, validation,
                       escalations_so_far, high_cost_wh, high_cost_usd,
                       MODEL_CATALOG if catalog is None else catalog)
    except Exception:
        # N1: "if the cap check errors, do not escalate" -- and the same safe
        # direction for any other error. Loud in the log, never silent.
        log.exception("repair router errored; withholding rather than escalating")
        return _withhold("repair_router_error",
                         "an internal error occurred while deciding on repair; not escalating")


def _decide(plan, tier_used, kind, request_text, validation,
            escalations_so_far, high_cost_wh, high_cost_usd, catalog) -> RepairDecision:
    if not isinstance(kind, FailureKind):
        return _withhold("invalid_failure_kind", f"got {kind!r}")

    # --- N1: the bound -------------------------------------------------------
    if (isinstance(escalations_so_far, bool) or not isinstance(escalations_so_far, int)
            or escalations_so_far < 0):
        return _withhold("invalid_escalation_count", f"got {escalations_so_far!r}")
    if escalations_so_far >= MAX_ESCALATIONS:
        return _withhold("escalation_bound_reached",
                         f"already escalated {escalations_so_far} time(s); the limit is {MAX_ESCALATIONS}")

    # --- failure-specific rules ---------------------------------------------
    if kind is FailureKind.VALIDATION_FAILED:
        if validation is None:
            return _withhold("missing_validation_result", "a validation failure needs its result")
        if validation.passed:
            return _withhold("nothing_to_repair", "validation passed")
        if validation.validator_errored:
            return _withhold("validator_unavailable",
                             "the validator itself errored; a retry would be unvalidated too")
        unsafe = sorted({c.name for c in validation.checks if not c.passed} & NON_REPAIRABLE_CHECKS)
        if unsafe:
            return _withhold("safety_failure_not_retried",
                             f"failed safety check(s) {unsafe}; a safety signal is not a capability gap")

    # --- target: strictly upward --------------------------------------------
    if tier_used is MethodTier.LLM_HIGH_REASONING:
        return _withhold("no_higher_tier", "already at the highest tier")
    step_used = plan.step_for(tier_used)
    if step_used is None or not step_used.attempt:
        return _withhold("tier_not_in_plan", f"{tier_used!r} was not an attempted tier in this plan")

    if tier_used in _BELOW_LLM:
        target = MethodTier.LLM_LOW_REASONING
        step_llm = plan.step_for(MethodTier.LLM_LOW_REASONING)
        target_est = step_llm.estimate
        target_model = step_llm.model_name
        skip_note = (f"skipped intermediate non-LLM rungs above {tier_used.value}: a failed cheaper "
                     f"answer is repaired by a language model")
    elif tier_used is MethodTier.LLM_LOW_REASONING:
        target = MethodTier.LLM_HIGH_REASONING
        target_model = step_used.model_name
        target_est = estimate_tier(target, request_text, _find_model(target_model, catalog),
                                   plan.classification.category)
        skip_note = "same model, deeper reasoning"
    else:  # unknown tier value
        return _withhold("unsupported_tier", f"{tier_used!r}")

    # --- N1: cumulative worst-case must stay inside the cost-gate limits -----
    wh_limit = _limit("high_cost_wh", high_cost_wh)
    usd_limit = _limit("high_cost_usd", high_cost_usd)
    spent_wh, spent_usd = _spent_upper_bound(plan, tier_used)
    total_wh = spent_wh + target_est.wh_high
    total_usd = spent_usd + target_est.tier_estimate.est_dollar_cost
    if not (math.isfinite(total_wh) and math.isfinite(total_usd)):
        return _withhold("cap_check_error", "cumulative estimate was not finite; not escalating")
    if total_wh >= wh_limit or total_usd >= usd_limit:
        return _withhold(
            "cost_ceiling",
            f"worst-case cumulative {total_wh:.3f} Wh / ${total_usd:.4f} including {target.value} "
            f"would reach the limit ({wh_limit:g} Wh / ${usd_limit:g}); not escalating")

    return RepairDecision(
        RepairAction.ESCALATE, "escalate_once",
        f"{kind.value} on {tier_used.value}; escalating once to {target.value} ({skip_note}); "
        f"worst-case cumulative {total_wh:.3f} Wh / ${total_usd:.4f}",
        target, target_model, total_wh, total_usd, target_est.tier_estimate)
