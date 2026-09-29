
"""Stage 3 — model selection.

Separate from tiers/llm_call.py on purpose (per README): this module SCORES
candidate models on cost vs. capability vs. latency and picks one; llm_call.py
only EXECUTES the call once a model has been chosen.

Only applies to tiers that take a model (RAG_SMALL_MODEL, LLM_LOW_REASONING,
LLM_HIGH_REASONING) -- see cost.estimator.LLM_TIERS.

Failure behavior (ARCHITECTURE.md Stage 3, req. 7): if no candidate meets the
capability floor, escalate to the most capable model available rather than
the cheapest -- "default to the most conservative tier ... not the cheapest."
"""
from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Optional, Sequence

from cost.estimator import LLM_TIERS, CostEstimate, estimate_tier
from cost.model_registry import MODEL_CATALOG, ModelInfo
from policy.schemas import MethodTier, RequestType

OBJECTIVES = ("energy", "dollar")


def _objective_value(estimate: CostEstimate, objective: str) -> float:
    return (estimate.tier_estimate.est_energy_wh if objective == "energy"
            else estimate.tier_estimate.est_dollar_cost)


@dataclass(frozen=True)
class CandidateResult:
    """One catalog model's estimate for this request, for the audit trail."""
    model_name: str
    capability_score: float
    meets_capability: bool
    estimate: CostEstimate


@dataclass(frozen=True)
class SelectionResult:
    model: ModelInfo
    estimate: CostEstimate
    rationale: str
    escalated: bool
    objective: str
    # Every candidate considered, cheapest-by-objective first (audit req.: "which
    # cheaper [options] were tried and rejected and why").
    alternatives: tuple[CandidateResult, ...]


def _validate_min_capability(min_capability) -> float:
    if isinstance(min_capability, bool) or not isinstance(min_capability, numbers.Real):
        raise TypeError(f"min_capability must be a real number, got {min_capability!r}")
    value = float(min_capability)
    if not math.isfinite(value):
        raise ValueError(f"min_capability must be finite, got {min_capability!r}")
    return value


def select_model(
    tier: MethodTier,
    request_text: str,
    *,
    request_type: RequestType = RequestType.UNKNOWN,
    expected_output_tokens: Optional[int] = None,
    min_capability: float = 0.0,
    objective: str = "energy",
    catalog: Optional[Sequence[ModelInfo]] = None,
) -> SelectionResult:
    """Pick the cheapest catalog model meeting `min_capability` for this request.

    Raises ValueError for a non-LLM tier, an empty catalog, an unknown
    objective, or a non-finite min_capability. Raises TypeError for a
    non-numeric min_capability or a catalog entry that isn't a ModelInfo.
    """
    if tier not in LLM_TIERS:
        raise ValueError(f"model_selector only applies to LLM-capable tiers "
                         f"{sorted(t.value for t in LLM_TIERS)}, got {tier!r}")
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}, got {objective!r}")
    min_capability = _validate_min_capability(min_capability)

    pool = MODEL_CATALOG if catalog is None else catalog
    if len(pool) == 0:
        raise ValueError("catalog is empty: no model available to select")
    for m in pool:
        if not isinstance(m, ModelInfo):
            raise TypeError(f"catalog entries must be ModelInfo, got {type(m).__name__}")

    candidates = []
    for model in pool:
        est = estimate_tier(tier, request_text, model, request_type, expected_output_tokens)
        candidates.append(CandidateResult(
            model.name, model.capability_score, model.capability_score >= min_capability, est))

    by_name = {m.name: m for m in pool}
    ranked_all = tuple(sorted(candidates, key=lambda c: _objective_value(c.estimate, objective)))

    qualifying = [c for c in candidates if c.meets_capability]
    if qualifying:
        # Cheapest first; ties broken toward the least-overqualified model, then by
        # name, so the result never depends on catalog order.
        best = min(qualifying, key=lambda c: (_objective_value(c.estimate, objective),
                                              c.capability_score, c.model_name))
        escalated = False
        rationale = (
            f"Selected {best.model_name} (capability {best.capability_score:g} >= floor "
            f"{min_capability:g}), cheapest by {objective} among {len(qualifying)} "
            f"qualifying of {len(candidates)} candidates: "
            + ", ".join(f"{c.model_name}={_objective_value(c.estimate, objective):.6g}"
                       for c in ranked_all) + "."
        )
    else:
        # Nobody clears the floor: fail toward capability, not cost (Stage 3, req. 7).
        best = max(candidates, key=lambda c: (c.capability_score, c.model_name))
        escalated = True
        rationale = (
            f"No candidate met min_capability {min_capability:g} (best available: "
            f"{', '.join(f'{c.model_name}={c.capability_score:g}' for c in candidates)}). "
            f"Escalated to the highest-capability model, {best.model_name}, per the "
            f"fail-conservative rule rather than picking the cheapest."
        )

    return SelectionResult(
        model=by_name[best.model_name],
        estimate=best.estimate,
        rationale=rationale,
        escalated=escalated,
        objective=objective,
        alternatives=ranked_all,
    )
