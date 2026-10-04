
"""
api/main.py — Stage 0 -> Stage 1 -> Stage 2 (session) -> Stage 3/5 (tier
ladder) -> Stage 6 (validator, one bounded repair) -> Stage 7 (audit).

Stage 4 (interface/feedforward.py) is wired after Stage 3 planning: cost gate plus route preview/outcome.

REQUIRE_HUMAN (Stage 1 or session-derived) is satisfied by a confirm-before-execute checkpoint (interface/human_checkpoint.py): 
the first call returns needs_confirmation plus a single-use token bound to session, exact text, and rule set; 
the caller re-submits with the token to proceed. A token never overrides a BLOCK.

--- Sprint 5 additions (Stage 6 validation + bounded repair; OI-064/OI-066) ---

Every answer from every tier, cache hits included, is validated (validation/
validator.py, non-LLM checks only) BEFORE it is released. On a validation
failure or a Stage 5 execution error, escalation/repair_router.py decides
between ONE upward escalation and WITHHOLD (provisional bound, OI-065). The
escalated answer is validated again; a second failure is a WITHHOLD.

WITHHOLD (OI-066, owner decision) is an explicit non-success outcome: the
generated output is NOT returned as an ordinary answer, the response says that
a releasable response could not be established, and nothing implies that a
human reviewed or approved anything (no human-release path exists yet). It is
reported as blocked=True with block_reason output_withheld_validation_failed /
output_withheld_validator_error / output_withheld_execution_error, so the three
causes stay distinguishable. The audit record carries execution=
"executed_withheld" plus a validation_trace.

Caching: an answer is stored in the cache only after it genuinely passed
validation (never after a failed check, a withheld answer, or a validator
error that was released fail-open). A cache hit that fails validation goes
through repair like any other failure, and a validated repair overwrites the
bad entry.

Validation outcomes are NOT fed into Stage 2 session risk (owner decision).

--- Sprint 3 additions (session context + cost accounting) ---

Stage 2 ordering: record_turn() is called exactly ONCE per request, right
after Stage 0/1 and BEFORE Stage 3/5, with turn_cost=0.0. This matches
ARCHITECTURE.md's stage ordering (Stage 2 gates before Stage 3 ever runs)
and never wastes an execution on a request session history was going to
escalate anyway. The tradeoff, logged as OI-036: SessionState.cumulative_cost
never sees a turn's REAL dollar cost this sprint, only its risk signal --
a turn's own cost isn't known until Stage 3/5 runs, and folding it in only
after the fact would mean gating THIS turn on a total that doesn't include
it, which is correct, but calling record_turn a second time to add it would
double-count turn_count and risk. The real per-turn cost/energy still reaches
the audit log in full via the estimator; only the session's cumulative-cost
*threshold* is approximate this sprint. Threading a pre-execution cost
estimate into the gate is future (post-Sprint-3) work.

Combined action: after Stage 1, combined = max(most_severe, session
constraints.min_action) by severity (session may only TIGHTEN, never
loosen, per the ARCHITECTURE.md core principle). "A Stage-1 BLOCK is 
already terminal and unaffected by this (REQUIRE_HUMAN is terminal 
until a valid confirmation token is presented)". The new case this 
creates is a request Stage 1 alone would ALLOW/FLAG, but that session 
history pushes to REQUIRE_HUMAN/BLOCK -- new block_reason values 
"session_require_human" / "session_block" mark this distinctly from 
Stage 1's own "policy_gate" / "human_confirmation_required".

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
import logging
from dataclasses import asdict, dataclass, replace
from typing import Optional

from api.settings import settings
from interface.human_checkpoint import CheckpointManager, confirmation_message
from interface.feedforward import (
    GATE_COST_ID, evaluate_gate, safe_escalation_outcome, safe_outcome, safe_preview,
    safe_worst_case_estimate,
)

from escalation.repair_router import (
    FailureKind, RepairAction, WITHHELD_MESSAGE, WITHHELD_MESSAGE_EXECUTION_ERROR,
    WITHHELD_MESSAGE_VALIDATOR_ERROR, decide_repair,
)
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
from validation.validator import ValidationResult, validate_output

log = logging.getLogger(__name__)

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

_LLM_TIERS = (MethodTier.LLM_LOW_REASONING, MethodTier.LLM_HIGH_REASONING)

# User-facing validation wording (owner decision): "passed automated checks",
# never "verified". The second string is used when the validator itself errored
# and the answer was released under the low-stakes (fail-open) policy.
VALIDATION_PASSED = "passed automated checks"
VALIDATION_NOT_COMPLETED = ("not validated: automated checks could not be completed for this "
                            "answer (released under the low-stakes failure policy)")

# Module-level singleton, swappable like tiers.cache_lookup's _client
# (tests reassign this directly for isolation -- see configure_session_manager).

_session_manager = SessionManager()


def configure_session_manager(manager: SessionManager) -> None:
    global _session_manager
    _session_manager = manager


_checkpoint = CheckpointManager(secret=settings.checkpoint_secret or None)



def configure_checkpoint(manager: CheckpointManager) -> None:
    global _checkpoint
    _checkpoint = manager


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
    needs_confirmation: bool = False
    confirmation_token: str | None = None
    feedforward: str | None = None
    validation_status: str | None = None


def _run_tier(tier: MethodTier, text: str, model_name: Optional[str]) -> Optional[str]:
    """Execute ONE tier once (Stage 5). Returns the answer, or None when a
    non-LLM rung cannot answer. Exceptions propagate to the caller, which
    treats them as Stage 5 execution errors."""
    if tier in _LLM_TIERS:
        return call_llm(text, model_name=model_name)
    return _TIER_FUNCS[tier](text)


def _new_trace(first_tier: MethodTier, plan) -> dict:
    """Structured Stage 6 / repair record for the audit log (OI-066). Keeps
    validation failure, validator error, repair attempted, repair
    unavailable/exhausted, and the final outcome separately distinguishable."""
    step = plan.step_for(first_tier)
    return {
        "check_type": "non_llm",
        "first_attempt_tier": first_tier.value,
        "first_attempt_estimate": asdict(step.estimate.tier_estimate) if step else None,
        "execution_error": False,
        "validation_failed": False,
        "validator_error": False,
        "failed_open": False,
        "failed_checks": [],
        "repair_attempted": False,
        # not_needed | succeeded | exhausted (attempted, still not releasable)
        # | unavailable (router refused to attempt one)
        "repair_status": "not_needed",
        "repair_reason": None,
        "repair_target_tier": None,
        "events": [],
        "final": None,
    }


def _record_validation(trace: dict, tier: MethodTier, v: ValidationResult) -> None:
    failed = [c.name for c in v.checks if not c.passed]
    if v.validator_errored:
        trace["validator_error"] = True
    if v.failed_open:
        trace["failed_open"] = True
    if not v.passed and not v.validator_errored:
        trace["validation_failed"] = True
    for name in failed:
        if name not in trace["failed_checks"]:
            trace["failed_checks"].append(name)
    trace["events"].append({
        "event": "validation", "tier": tier.value, "passed": v.passed,
        "validator_errored": v.validator_errored, "failed_open": v.failed_open,
        "failed_checks": failed, "reason": v.reason,
    })


def _record_repair_decision(trace: dict, d) -> None:
    trace["events"].append({
        "event": "repair_decision", "action": d.action.value, "reason": d.reason, "detail": d.detail,
        "target_tier": d.target_tier.value if d.target_tier else None,
        "worst_case_wh_high": d.worst_case_wh_high, "worst_case_usd": d.worst_case_usd,
    })


def process_request(text: str, session_id: str | None = None, confirmation_token: str | None = None) -> PipelineResult:
    """The actual Stage 0 -> 1 -> 2 -> 3/5 -> 6 -> 7 pipeline. No FastAPI/pydantic
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
        ), stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot(), execution="blocked")
        return PipelineResult(response="This request could not be processed.",
                               tier_used="blocked_stage0", blocked=True, block_reason="stage0_screen")

    normalized = screen_result.normalized_text

    # --- Stage 1 ---
    flags, most_severe = get_policy_engine().evaluate(normalized)
    rule_ids = [f.rule_id for f in flags]

    # --- Human confirmation (Stage 1 #10 / Stage 4 / Stage 7) ---
    # A token can only satisfy REQUIRE_HUMAN. It is never examined for a
    # Stage 1 BLOCK; it is single-use and bound to session + exact text + rules.
    confirmation = None
    ack_cost = False
    if confirmation_token is not None and most_severe != PolicyAction.BLOCK:
        confirmation = _checkpoint.verify_and_consume(confirmation_token, session_id, normalized, rule_ids)
        if not confirmation.ok and confirmation.reason == "bad_signature":
            with_cost = _checkpoint.verify_and_consume(
                confirmation_token, session_id, normalized, rule_ids + [GATE_COST_ID])
            if with_cost.ok or with_cost.reason != "bad_signature":
                confirmation, ack_cost = with_cost, with_cost.ok
    confirmed = bool(confirmation and confirmation.ok)

    # --- Stage 2 --- (one call per request; see module docstring on ordering/OI-036)
    # A consumed token means these flags were already charged when it was issued.
    state, constraints = _session_manager.record_turn(session_id, [] if confirmed else flags, verdict_str, 0.0)
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
        ), stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot(), execution="blocked")
        return PipelineResult(response="This request violates policy and cannot be processed.",
                               tier_used="blocked_stage1",
                               blocked=True,
                               block_reason="session_block" if session_escalated else "policy_gate")

    # --- Stage 3 (pure planning: no model call, nothing executes) ---
    plan = plan_request(normalized)

    # --- Stage 4: feedforward + hard confirm gates ---
    gate = evaluate_gate(plan)
    human_needed = combined == PolicyAction.REQUIRE_HUMAN and not confirmed
    cost_needed = gate.required and not ack_cost
    if human_needed or cost_needed:
        if human_needed and most_severe == PolicyAction.REQUIRE_HUMAN:
            reasons = [f.reason for f in flags if f.action == PolicyAction.REQUIRE_HUMAN]
            rationale = f"Stage 1 flagged REQUIRE_HUMAN ({rule_ids})."
        elif human_needed:
            reasons = list(constraints.reasons)
            rationale = (f"This message's own Stage 1 result was {most_severe.value}, but session-level "
                         f"escalation raised it to REQUIRE_HUMAN: cumulative session risk/cost crossed the "
                         f"threshold ({', '.join(constraints.reasons)}).")
        else:
            reasons, rationale = [], "Stage 4 high-cost gate."
        if cost_needed:
            reasons += list(gate.reasons)
            rationale += f" Stage 4 high-cost gate: {'; '.join(gate.reasons)}."
        rationale += (" Execution withheld until the caller re-submits with a valid "
                      "human-confirmation token.")
        if confirmation is not None and not confirmation.ok:
            rationale += f" Previous confirmation rejected ({confirmation.reason})."
        preview = safe_preview(plan)
        rationale += (" Feedforward shown before execution." if preview
                      else " Feedforward unavailable (render error).")
        token = _checkpoint.issue(session_id, normalized,
                                  rule_ids + ([GATE_COST_ID] if gate.required else []))
        log_decision(session_id, RoutingDecision(
            selected_tier=MethodTier.CACHE, selected_model=None, rationale=rationale,
            cost_estimate=TierCostEstimate(tier=MethodTier.CACHE), policy_flags=flags,
        ), stage0_screen_result=verdict_str, session_state_snapshot=state.snapshot(), 
                     execution="withheld_pending_confirmation", 
                     withheld_route_estimate=safe_worst_case_estimate(plan))
        message = confirmation_message(reasons, _checkpoint.ttl_seconds)
        if preview:
            message += " " + preview
        if human_needed:
            block_reason = "session_require_human" if session_escalated else "human_confirmation_required"
        else:
            block_reason = "cost_confirmation_required"
        return PipelineResult(
            response=message,
            tier_used="blocked_stage1_human_required" if human_needed else "blocked_stage4_cost_gate",
            blocked=True, block_reason=block_reason,
            needs_confirmation=True, confirmation_token=token, feedforward=preview)

    # --- Stage 5: execute the plan, cheapest first ---
    tier_used = None
    result_text = None
    exec_error = False
    for tier in plan.attempt_order:
        tier_used = tier
        try:
            result_text = _run_tier(tier, normalized, plan.step_for(tier).model_name)
        except Exception:
            log.exception("Stage 5 execution error on tier %s", tier.value)
            exec_error = True
            break
        if result_text is not None:
            break
    if result_text is None and not exec_error:
        raise RuntimeError("routing plan had no terminal tier")

    # --- Stage 6: validate before anything is released (cache hits included) ---
    trace = _new_trace(tier_used, plan)
    latest_exec_error = exec_error
    latest_validation: Optional[ValidationResult] = None
    released = False
    final_tier, final_text, final_validation = tier_used, result_text, None
    repair = None
    attempted_repair = False

    if exec_error:
        trace["execution_error"] = True
        trace["events"].append({"event": "execution_error", "tier": tier_used.value})
    else:
        latest_validation = validate_output(normalized, result_text, tier_used, flags)
        _record_validation(trace, tier_used, latest_validation)
        released = latest_validation.passed
        final_validation = latest_validation

    # --- Bounded repair (escalation/repair_router.py): at most one escalation ---
    if not released:
        kind = FailureKind.EXECUTION_ERROR if exec_error else FailureKind.VALIDATION_FAILED
        repair = decide_repair(plan, tier_used, kind, normalized,
                               validation=latest_validation, escalations_so_far=0)
        trace["repair_reason"] = repair.reason
        _record_repair_decision(trace, repair)

        if repair.action is RepairAction.ESCALATE:
            attempted_repair = True
            trace["repair_attempted"] = True
            trace["repair_target_tier"] = repair.target_tier.value
            repaired_text = None
            try:
                repaired_text = _run_tier(repair.target_tier, normalized, repair.target_model)
            except Exception:
                log.exception("Stage 5 execution error on repair tier %s", repair.target_tier.value)
            if repaired_text is None:
                latest_exec_error = True
                latest_validation = None
                trace["execution_error"] = True
                trace["events"].append({"event": "execution_error", "tier": repair.target_tier.value,
                                        "during": "repair"})
                bound = decide_repair(plan, repair.target_tier, FailureKind.EXECUTION_ERROR, normalized,
                                      escalations_so_far=1)
            else:
                latest_exec_error = False
                latest_validation = validate_output(normalized, repaired_text, repair.target_tier, flags)
                _record_validation(trace, repair.target_tier, latest_validation)
                if latest_validation.passed:
                    released = True
                    final_tier, final_text, final_validation = (
                        repair.target_tier, repaired_text, latest_validation)
                    trace["repair_status"] = "succeeded"
                    bound = None
                else:
                    bound = decide_repair(plan, repair.target_tier, FailureKind.VALIDATION_FAILED,
                                          normalized, validation=latest_validation, escalations_so_far=1)
            if bound is not None:
                trace["repair_status"] = "exhausted"
                trace["repair_reason"] = bound.reason
                _record_repair_decision(trace, bound)
        else:
            trace["repair_status"] = "unavailable"

    # --- Stage 7 (partial): decision for the last step that actually ran ---
    if attempted_repair:
        decision = RoutingDecision(
            selected_tier=repair.target_tier,
            selected_model=repair.target_model,
            rationale=(f"{repair.target_tier.value} ran as the one repair escalation "
                       f"({repair.detail}). {plan.rationale}"),
            cost_estimate=repair.target_cost or TierCostEstimate(tier=repair.target_tier),
            policy_flags=list(flags),
        )
    else:
        decision = plan.decision_for(tier_used, flags)
    if confirmed:
        ack = "; high-cost gate acknowledged" if ack_cost else ""
        decision = replace(decision, rationale=f"human confirmation accepted (token {confirmation.nonce}{ack}); "
                                               + decision.rationale)

    if released:
        trace["final"] = "released"
        # Cache only what genuinely passed validation: not a validator error released
        # fail-open, and not a cache hit (its TTL is not refreshed). A validated
        # repair overwrites a bad cache entry.
        if final_tier != MethodTier.CACHE and final_validation.passed and not final_validation.failed_open:
            store_cache_entry(normalized, final_text)

        if attempted_repair:
            tc = repair.target_cost
            outcome = safe_escalation_outcome(
                tier_used, final_tier, repair.target_model,
                tc.est_energy_wh if tc else 0.0, tc.est_dollar_cost if tc else 0.0)
        else:
            outcome = safe_outcome(plan, final_tier)
        decision = replace(decision, rationale=decision.rationale + (
            " Feedforward attached to response." if outcome else " Feedforward unavailable (render error)."))
        log_decision(session_id, decision, stage0_screen_result=verdict_str,
                     session_state_snapshot=state.snapshot(), execution="executed",
                     validation_trace=trace)
        status = (VALIDATION_PASSED if final_validation.passed and not final_validation.failed_open
                  else VALIDATION_NOT_COMPLETED)
        return PipelineResult(response=final_text, tier_used=final_tier.value, blocked=False,
                              block_reason=None, feedforward=outcome, validation_status=status)

    # --- WITHHOLD (OI-066): non-success outcome, nothing released, nothing cached ---
    if latest_exec_error:
        failure, message = "execution_error", WITHHELD_MESSAGE_EXECUTION_ERROR
    elif latest_validation is not None and latest_validation.validator_errored:
        failure, message = "validator_error", WITHHELD_MESSAGE_VALIDATOR_ERROR
    else:
        failure, message = "validation_failed", WITHHELD_MESSAGE
    trace["final"] = f"withheld_{failure}"
    decision = replace(decision, rationale=(
        f"Output withheld ({failure}; repair {trace['repair_status']}: {trace['repair_reason']}). "
        + decision.rationale))
    log_decision(session_id, decision, stage0_screen_result=verdict_str,
                 session_state_snapshot=state.snapshot(), execution="executed_withheld",
                 validation_trace=trace)
    return PipelineResult(response=message, tier_used="withheld_stage6", blocked=True,
                          block_reason=f"output_withheld_{failure}")


# --- FastAPI glue (thin wrapper around process_request) ---
try:
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="Constitutional Runtime")

    class RequestIn(BaseModel):
        text: str
        session_id: str | None = None
        confirmation_token: str | None = None

    class ResponseOut(BaseModel):
        response: str
        tier_used: str
        blocked: bool
        block_reason: str | None = None
        needs_confirmation: bool = False
        confirmation_token: str | None = None
        feedforward: str | None = None
        validation_status: str | None = None

    @app.post("/v1/respond", response_model=ResponseOut)
    def respond(req: RequestIn) -> ResponseOut:
        result = process_request(req.text, req.session_id, req.confirmation_token)
        return ResponseOut(**result.__dict__)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

except ImportError:
    app = None
