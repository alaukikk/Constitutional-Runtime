
"""
api/main.py — Stage 0 -> Stage 1 -> Stage 3/5 (tier ladder) -> Stage 7 (audit).

Stage 2 (session), Stage 4 (feedforward), Stage 6 (validator) are NOT wired
here yet -- those are Sprint 3-5 scope per docs/EXECUTION_PLAN.md, not a
backlog gap in this file.

Known gap, resolved per the letter of the frozen spec rather than a style
preference: ARCHITECTURE.md Stage 1 #10 says REQUIRE_HUMAN "flows through,
but Stage 4/7 MUST enforce a human checkpoint before or after execution."
interface/human_checkpoint.py doesn't exist yet, so that requirement cannot
be satisfied -- meaning execution must not proceed, per the spec's own
wording. process_request() therefore BLOCKS REQUIRE_HUMAN requests until
the real checkpoint is implemented (Sprint 4+), rather than answering
anyway with just a log note.

Design note: the actual pipeline logic lives in process_request(), a plain
function with no FastAPI/pydantic dependency. The FastAPI route below is a
thin wrapper around it.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass

from guardrails.injection_screen import screen_request, ScreenVerdict
from policy.engine import get_policy_engine
from policy.schemas import PolicyAction, MethodTier, RoutingDecision, TierCostEstimate
from tiers.cache_lookup import try_cache_lookup, store_cache_entry
from tiers.deterministic import try_deterministic
from tiers.small_classifier import try_small_classifier
from tiers.rag_small_model import try_rag_small_model
from tiers.llm_call import call_llm
from audit.audit_log import log_decision

# Cheapest-first per ARCHITECTURE.md Stage 3 #4. Cache is NOT a bypass of
# Stage 0/1 -- it's simply first in this ladder, evaluated only after both
# have already passed.
_TIER_LADDER = [
    (MethodTier.CACHE, try_cache_lookup),
    (MethodTier.DETERMINISTIC, try_deterministic),
    (MethodTier.SMALL_CLASSIFIER, try_small_classifier),
    (MethodTier.RAG_SMALL_MODEL, try_rag_small_model),
]


@dataclass
class PipelineResult:
    response: str
    tier_used: str
    blocked: bool
    block_reason: str | None


def process_request(text: str, session_id: str | None = None) -> PipelineResult:
    """The actual Stage 0 -> 1 -> 3/5 -> 7 pipeline. No FastAPI/pydantic
    dependency, so this can be tested directly without a running server."""
    session_id = session_id or str(uuid.uuid4())

    # --- Stage 0 ---
    screen_result = screen_request(text)
    if screen_result.verdict == ScreenVerdict.BLOCKED:
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE,
            selected_model=None,
            rationale=f"Stage 0 blocked request before Stage 1 ran. Matched patterns: {screen_result.matched_patterns}",
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE),
            policy_flags=[],
        ))
        return PipelineResult(response="This request could not be processed.",
                               tier_used="blocked_stage0", blocked=True, block_reason="stage0_screen")

    normalized = screen_result.normalized_text

    # --- Stage 1 ---
    flags, most_severe = get_policy_engine().evaluate(normalized)
    if most_severe == PolicyAction.BLOCK:
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE,
            selected_model=None,
            rationale=f"Stage 1 blocked request. Triggered rules: {[f.rule_id for f in flags]}",
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE),
            policy_flags=flags,
        ))
        return PipelineResult(response="This request violates policy and cannot be processed.",
                               tier_used="blocked_stage1", blocked=True, block_reason="policy_gate")

    if most_severe == PolicyAction.REQUIRE_HUMAN:
        # ARCHITECTURE.md Stage 1 #10: a human checkpoint MUST be enforced
        # before execution for these. It doesn't exist yet (Sprint 4+), so
        # execution cannot proceed -- this isn't optional caution, it's what
        # the frozen spec already requires.
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE,
            selected_model=None,
            rationale=(
                f"Stage 1 flagged REQUIRE_HUMAN ({[f.rule_id for f in flags]}). "
                f"interface/human_checkpoint.py not yet implemented, so the mandatory "
                f"human checkpoint (ARCHITECTURE.md Stage 1 #10) cannot be satisfied. "
                f"Execution blocked rather than proceeding without it."
            ),
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE),
            policy_flags=flags,
        ))
        return PipelineResult(
            response="This request requires human review before it can be answered, "
                     "and that review step isn't available yet. Please consult a "
                     "qualified professional directly for this.",
            tier_used="blocked_stage1_human_required",
            blocked=True,
            block_reason="human_checkpoint_unavailable",
        )

    # --- Stage 3/5 ---
    tier_used = None
    result_text = None
    for tier, fn in _TIER_LADDER:
        candidate = fn(normalized)
        if candidate is not None:
            tier_used, result_text = tier, candidate
            break

    if result_text is None:
        tier_used = MethodTier.LLM_LOW_REASONING
        result_text = call_llm(normalized)
        store_cache_entry(normalized, result_text)
    elif tier_used != MethodTier.CACHE:
        # Populate the cache for next exact repeat. Don't re-store a value
        # that was ITSELF a cache hit -- that would just refresh its TTL
        # for no reason.
        store_cache_entry(normalized, result_text)

    # --- Stage 7 (partial -- audit_log.py is the Sprint 1 subset schema) ---
    log_decision(session_id, RoutingDecision(
        selected_tier=tier_used,
        selected_model="stub-model" if tier_used == MethodTier.LLM_LOW_REASONING else None,
        rationale=f"First tier in cheapest-first ladder to return non-None: {tier_used.value}",
        cost_estimate=TierCostEstimate(tier=tier_used),
        policy_flags=flags,
    ))

    return PipelineResult(response=result_text, tier_used=tier_used.value, blocked=False, block_reason=None)


# --- FastAPI glue (thin wrapper around process_request) ---
try:
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="Constitutional Runtime")

    class RequestIn(BaseModel):
        text: str
        session_id: str | None = None

    class ResponseOut(BaseModel):
        response: str
        tier_used: str
        blocked: bool
        block_reason: str | None = None

    @app.post("/v1/respond", response_model=ResponseOut)
    def respond(req: RequestIn) -> ResponseOut:
        result = process_request(req.text, req.session_id)
        return ResponseOut(**result.__dict__)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

except ImportError:
    app = None
