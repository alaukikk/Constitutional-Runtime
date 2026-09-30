
"""
api/main.py — Stage 0 -> Stage 1 -> Stage 2 (session) -> Stage 3/5 (tier
ladder) -> Stage 7 (audit).

Stage 4 (feedforward), Stage 6 (validator) are NOT wired here yet -- Sprint
4-5 scope per docs/EXECUTION_PLAN.md, not a backlog gap in this file.

Known gap, resolved per the letter of the frozen spec rather than a style
preference: ARCHITECTURE.md Stage 1 #10 says REQUIRE_HUMAN "flows through,
but Stage 4/7 MUST enforce a human checkpoint before or after execution."
interface/human_checkpoint.py doesn't exist yet, so that requirement cannot
be satisfied -- meaning execution must not proceed, per the spec's own
wording. process_request() therefore BLOCKS REQUIRE_HUMAN requests until
the real checkpoint is implemented (Sprint 4+), rather than answering
anyway with just a log note.

--- Sprint 3 additions (session context + cost accounting) ---

Stage 2 ordering: record_turn() is called exactly ONCE per request, right
after Stage 0/1 and BEFORE Stage 3/5, with turn_cost=0.0. This matches
ARCHITECTURE.md's stage ordering (Stage 2 gates before Stage 3 ever runs)
and never wastes an execution on a request session history was going to
escalate anyway. The tradeoff, logged as OI-027: SessionState.cumulative_cost
never sees a turn's REAL dollar cost this sprint, only its risk signal --
a turn's own cost isn't known until Stage 3/5 runs, and folding it in only
after the fact would mean gating THIS turn on a total that doesn't include
it, which is correct, but calling record_turn a second time to add it would
double-count turn_count and risk. The real per-turn cost/energy still reaches
the audit log in full via the estimator; only the session's cumulative-cost
*threshold* is approximate this sprint. Threading a pre-execution cost
estimate into the gate is future (post-Sprint-3) work.

Combined action: after Stage 1, `combined = max(most_severe, session
constraints.min_action)` by severity (session may only TIGHTEN, never
loosen, per the ARCHITECTURE.md core principle). A Stage-1 BLOCK/
REQUIRE_HUMAN is already terminal and unaffected by this (nothing is more
severe than BLOCK). The new case this creates is a request Stage 1 alone
would ALLOW/FLAG, but that session history pushes to REQUIRE_HUMAN/BLOCK --
new block_reason values "session_require_human" / "session_block" mark this
distinctly from Stage 1's own "policy_gate" / "human_checkpoint_unavailable".

Session ID: an absent session_id now maps to session.session_state's shared
ANONYMOUS_SESSION bucket instead of a fresh random uuid per call -- the old
behavior meant Stage 2 could never accumulate anything for anonymous
callers, which is worse than having no Stage 2 at all.
KNOWN LIMITATION, NOT fixed here (OI-013): a caller who supplies a
DIFFERENT session_id on every request still dodges Stage 2 entirely. This
function has no way to tell a rotated ID from a legitimately new user --
that requires server-side auth or a signed/issued session ID upstream of
this function, which doesn't exist anywhere in this repo yet.

_screen_verdict_str(): guardrails/injection_screen.py's ScreenVerdict isn't
otherwise referenced by name/shape here beyond the BLOCKED comparison this
file already made, so this normalizer works whether it's a str Enum, a
plain Enum, or a bare string -- it degrades to a lowercased passthrough
for anything unrecognized rather than crashing.
"""
from __future__ import annotations
from dataclasses import dataclass

from guardrails.injection_screen import screen_request, ScreenVerdict
from policy.engine import get_policy_engine
from policy.schemas import PolicyAction, MethodTier, RoutingDecision, TierCostEstimate
from tiers.cache_lookup import try_cache_lookup, store_cache_entry
from tiers.deterministic import try_deterministic
from tiers.small_classifier import try_small_classifier
from tiers.rag_small_model import try_rag_small_model
from tiers.llm_call import call_llm
from triage.decision import plan_request
from audit.audit_log import log_decision
from session.session_state import SessionManager, ANONYMOUS_SESSION, ACTION_ORDER

# Cheapest-first per ARCHITECTURE.md Stage 3 #4. Cache is NOT a bypass of
# Stage 0/1 -- it's simply first in this ladder, evaluated only after both
# have already passed (and, as of Sprint 3, after Stage 2 as well).
# Non-LLM rungs Stage 5 can execute. Which to try, and in what order, is decided
# by triage/decision.py's plan (Stage 3); the LLM rung is handled inline below.
_TIER_FUNCS = {
    MethodTier.CACHE: try_cache_lookup,
    MethodTier.DETERMINISTIC: try_deterministic,
    MethodTier.SMALL_CLASSIFIER: try_small_classifier,
    MethodTier.RAG_SMALL_MODEL: try_rag_small_model,
}

# Module-level singleton, swappable like tiers.cache_lookup's _client
# (tests reassign this directly for isolation -- see configure_session_manager).
_session_manager = SessionManager()


def configure_session_manager(manager: SessionManager) -> None:
    global _session_manager
    _session_manager = manager


def _screen_verdict_str(verdict) -> str:
    """Normalize a Stage 0 verdict to one of "clean"/"suspicious"/"blocked"
    (or a lowercased passthrough) regardless of how ScreenVerdict is shaped."""
    raw = str(getattr(verdict, "value", verdict)).lower()
    for known in ("blocked", "suspicious", "clean"):
        if known in raw:
            return known
    return raw


_SEVERE = {PolicyAction.BLOCK: "blocked_session", PolicyAction.REQUIRE_HUMAN: "human_required_session"}


@dataclass
class PipelineResult:
    response: str
    tier_used: str
    blocked: bool
    block_reason: str | None


def process_request(text: str, session_id: str | None = None) -> PipelineResult:
    """The actual Stage 0 -> 1 -> 2 -> 3/5 -> 7 pipeline. No FastAPI/pydantic
    dependency, so this can be tested directly without a running server."""
    session_id = session_id or ANONYMOUS_SESSION

    # --- Stage 0 ---
    screen_result = screen_request(text)
    verdict_str = _screen_verdict_str(screen_result.verdict)

    if screen_result.verdict == ScreenVerdict.BLOCKED:
        state, _ = _session_manager.record_turn(session_id, [], verdict_str, 0.0)
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE,
            selected_model=None,
            rationale=f"Stage 0 blocked request before Stage 1 ran. Matched patterns: {screen_result.matched_patterns}",
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE),
            policy_flags=[],
        ), stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot())
        return PipelineResult(response="This request could not be processed.",
                               tier_used="blocked_stage0", blocked=True, block_reason="stage0_screen")

    normalized = screen_result.normalized_text

    # --- Stage 1 ---
    flags, most_severe = get_policy_engine().evaluate(normalized)

    # --- Stage 2 --- (one call per request; see module docstring on ordering/OI-027)
    state, constraints = _session_manager.record_turn(session_id, flags, verdict_str, 0.0)
    combined = most_severe if ACTION_ORDER[most_severe] >= ACTION_ORDER[constraints.min_action] else constraints.min_action
    session_escalated = ACTION_ORDER[combined] > ACTION_ORDER[most_severe]

    if combined == PolicyAction.BLOCK:
        rationale = (f"Stage 1 blocked request. Triggered rules: {[f.rule_id for f in flags]}"
                    if most_severe == PolicyAction.BLOCK else
                    f"Session-level escalation blocked this request (this message's own Stage 1 "
                    f"result was {most_severe.value}); cumulative session risk/cost crossed the "
                    f"block threshold: {', '.join(constraints.reasons)}.")
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE, selected_model=None, rationale=rationale,
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE), policy_flags=flags,
        ), stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot())
        return PipelineResult(response="This request violates policy and cannot be processed.",
                               tier_used="blocked_stage1",
                               blocked=True,
                               block_reason="session_block" if session_escalated else "policy_gate")

    if combined == PolicyAction.REQUIRE_HUMAN:
        rationale = (
            f"Stage 1 flagged REQUIRE_HUMAN ({[f.rule_id for f in flags]}). "
            f"interface/human_checkpoint.py not yet implemented, so the mandatory "
            f"human checkpoint (ARCHITECTURE.md Stage 1 #10) cannot be satisfied. "
            f"Execution blocked rather than proceeding without it."
        ) if most_severe == PolicyAction.REQUIRE_HUMAN else (
            f"This message's own Stage 1 result was {most_severe.value}, but session-level "
            f"escalation raised it to REQUIRE_HUMAN: cumulative session risk/cost crossed the "
            f"threshold ({', '.join(constraints.reasons)}). Blocked because "
            f"interface/human_checkpoint.py, required before proceeding, isn't implemented yet."
        )
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE, selected_model=None, rationale=rationale,
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE), policy_flags=flags,
        ), stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot())
        return PipelineResult(
            response="This request requires human review before it can be answered, "
                     "and that review step isn't available yet. Please consult a "
                     "qualified professional directly for this.",
            tier_used="blocked_stage1_human_required",
            blocked=True,
            block_reason="session_require_human" if session_escalated else "human_checkpoint_unavailable",
        )

    # --- Stage 3/5 ---
    plan = plan_request(normalized)
    tier_used = None
    result_text = None
    for tier in plan.attempt_order:
        if tier == MethodTier.LLM_LOW_REASONING:
            tier_used = tier
            result_text = call_llm(normalized, model_name=plan.step_for(tier).model_name)
            break
        candidate = _TIER_FUNCS[tier](normalized)
        if candidate is not None:
            tier_used, result_text = tier, candidate
            break
    if result_text is None:
        raise RuntimeError("routing plan had no terminal tier")

    # Populate the cache for the next exact repeat; don't re-store a cache hit.
    if tier_used != MethodTier.CACHE:
        store_cache_entry(normalized, result_text)

    # --- Stage 7 (partial) ---
    log_decision(session_id, plan.decision_for(tier_used, flags),
                 stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot())

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
