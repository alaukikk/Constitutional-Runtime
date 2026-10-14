
"""
audit/audit_log.py -- Stage 7 permanent audit record, schema version 2 (CP-001, accepted
2026-10-13; target schema in ARCHITECTURE.md Stage 7).

Append-only JSON Lines. Lines without `schema_version` are version 1 and are never rewritten.
Every new line is version 2 and carries EVERY v2 field, using documented null / empty values
when a stage did not run -- an absent key and a "did not run" value are never the same thing.

WHAT THE RECORD NEVER CONTAINS: request text, redacted text, excerpts or n-grams. Text requests
are represented only by `request_evidence` (audit/request_evidence.py: a per-record-salted
HMAC). Every free-text-looking field here (rationale, trace reasons, escalation reasons) must
hold controlled identifiers and explanations only; tests/api/test_audit_schema_v2_pipeline.py
checks this end to end with a canary request.

KNOWN LIMIT (accepted by the owner, CP-001 A.5): an unflagged prompt-injection bypass cannot be
reconstructed from this record, because the request was never retained.

Unmeasured is never zero. `actual_cost.energy_wh` and `.dollars` are null until something
genuinely measures them; `latency_ms` is measured wall-clock execution time or null.

Audit-write problems fail loud (ARCHITECTURE.md Stage 7 #7): invalid values raise ValueError,
a missing HMAC key or salt raises AuditConfigError (audit/request_evidence.py), and nothing is
written in either case.
"""
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Sequence

from audit.request_evidence import validate_request_evidence
from policy.schemas import RoutingDecision

LOG_PATH = Path("audit_log.jsonl")

SCHEMA_VERSION = 2

# OI-058: a decision that prevented execution must not look like one that spent
# resources. Every record says which of these it is.
#
# "executed_withheld" (Sprint 5, OI-066): generation ran (or was attempted) but the output was
# NOT released -- validation failed, the validator could not complete, or execution failed,
# and no safe repair remained. Resources may have been spent, so `decision.cost_estimate` is
# the estimate for the last step that ran, not a zero placeholder. It does NOT mean a human
# reviewed anything.
EXECUTION_STATES = ("executed", "withheld_pending_confirmation", "blocked", "executed_withheld")

# States whose records may carry a validation_trace.
_TRACE_STATES = ("executed", "executed_withheld")

# States in which Stage 3/5 actually ran a tier: only these have a selected tier, an estimate
# of what ran, measured latency and escalation events. For the other two, the nested legacy
# `decision` holds an OI-058 placeholder; the top-level fields are null instead.
_RAN_STATES = ("executed", "executed_withheld")

# Stable terminal states (v2 `final_outcome`), derived from `execution`.
FINAL_OUTCOME_BY_EXECUTION = {
    "executed": "released",
    "blocked": "blocked",
    "withheld_pending_confirmation": "pending_confirmation",
    "executed_withheld": "withheld",
}

USER_CONFIRMATION_STATES = ("not_required", "pending", "confirmed")
CHECKPOINT_KINDS = ("human_required", "cost_gate")
ESCALATION_KINDS = ("ladder_fallthrough", "repair")

VALIDATION_RESULTS = ("passed", "failed", "validator_error_failed_open",
                      "validator_error_failed_closed", "not_run")


def validation_result_from_trace(validation_trace: Optional[dict]) -> str:
    """The v2 `validation_result` summary: the outcome of the LAST validation that actually ran.

    A normal failed check is "failed"; "failed open/closed" is used only when the validator
    ITSELF errored. No validation event (execution error before any answer, or a record where
    nothing ran) is "not_run".
    """
    events = (validation_trace or {}).get("events", []) if isinstance(validation_trace, dict) else []
    last = next((e for e in reversed(events) if e.get("event") == "validation"), None)
    if last is None:
        return "not_run"
    if last.get("validator_errored"):
        return "validator_error_failed_open" if last.get("failed_open") else "validator_error_failed_closed"
    return "passed" if last.get("passed") else "failed"


def _enum_value(x):
    return getattr(x, "value", x)


def _check_escalations(escalations: Sequence[dict]) -> list[dict]:
    out = []
    for i, ev in enumerate(escalations):
        if not isinstance(ev, dict):
            raise ValueError(f"escalations[{i}] must be a dict")
        if ev.get("kind") not in ESCALATION_KINDS:
            raise ValueError(f"escalations[{i}].kind must be one of {ESCALATION_KINDS}, got {ev.get('kind')!r}")
        for field_name in ("from_tier", "to_tier", "reason"):
            if not isinstance(ev.get(field_name), str) or not ev[field_name]:
                raise ValueError(f"escalations[{i}].{field_name} must be a non-empty string")
        out.append(dict(ev))
    return out


def log_decision(
    session_id: str,
    decision: RoutingDecision,
    *,
    execution: str,
    request_evidence: dict,
    outcome_reason: Optional[str],
    stage0_screen_result: Optional[str] = None,
    stage0_confidence: Optional[float] = None,
    stage0_matched_patterns: Optional[Sequence[str]] = None,
    session_state_snapshot: Optional[dict] = None,
    alternatives_considered: Optional[Sequence[dict]] = None,
    escalations: Optional[Sequence[dict]] = None,
    actual_latency_ms: Optional[float] = None,
    feedforward_returned: bool = False,
    user_confirmation_state: str = "not_required",
    checkpoint_kinds: Sequence[str] = (),
    withheld_route_estimate: Optional[dict] = None,
    validation_trace: Optional[dict] = None,
) -> None:
    """Append one schema-v2 record. See the module docstring and CP-001.

    Required (no default, so a forgotten call site fails loudly at its first call):
      execution        one of EXECUTION_STATES; `final_outcome` is derived from it.
      request_evidence the object from audit.request_evidence.build_request_evidence.
      outcome_reason   the controlled block/withhold reason code; None only when released.

    Stage fields -- None / empty means "that stage did not run" (documented per field):
      stage0_*               None when Stage 0 did not screen the request (non-text ingress
                             refusal); otherwise the verdict, confidence and matched PATTERN NAMES
                             (never matched text). [] means "screened, nothing matched".
      alternatives_considered the Stage 3 plan steps (tier, attempt, reason, estimate); [] when
                             no plan was made (blocked before Stage 3).
      escalations            transitions the pipeline actually made, each with a `kind`
                             (ladder_fallthrough | repair); [] when none happened or nothing ran.
      actual_latency_ms      measured Stage 5 wall-clock execution time across attempted tiers;
                             required for executed/executed_withheld, None otherwise.
      feedforward_returned   True only if the server put a feedforward message in its API
                             response. It does NOT mean the user saw it.
      user_confirmation_state not_required | pending | confirmed; server-observable states only
                             (cancelling or modifying in a UI cannot be observed and is not
                             recorded). pending <=> execution == withheld_pending_confirmation.
      checkpoint_kinds       why a checkpoint was required (human_required, cost_gate); a
                             checkpoint being required does not mean a human reviewed anything.

    Top-level `selected_tier` / `estimated_cost` are null when no tier ran (blocked and
    pending-confirmation records); the nested legacy `decision` is kept unchanged for
    compatibility and still holds the OI-058 placeholder there.
    """
    # ---- validate everything BEFORE touching the file: a bad value writes nothing ----
    if execution not in EXECUTION_STATES:
        raise ValueError(f"execution must be one of {EXECUTION_STATES}, got {execution!r}")
    ran = execution in _RAN_STATES
    evidence = validate_request_evidence(request_evidence)

    if withheld_route_estimate is not None and execution != "withheld_pending_confirmation":
        raise ValueError("withheld_route_estimate only applies to 'withheld_pending_confirmation' records")
    if validation_trace is not None and execution not in _TRACE_STATES:
        raise ValueError(f"validation_trace only applies to {_TRACE_STATES} records, got execution={execution!r}")

    if execution == "executed":
        if outcome_reason is not None:
            raise ValueError("a released ('executed') record must have outcome_reason None")
    elif not (isinstance(outcome_reason, str) and outcome_reason):
        raise ValueError(f"a {execution!r} record needs a non-empty outcome_reason code")

    if user_confirmation_state not in USER_CONFIRMATION_STATES:
        raise ValueError(f"user_confirmation_state must be one of {USER_CONFIRMATION_STATES}, "
                         f"got {user_confirmation_state!r}")
    if (user_confirmation_state == "pending") != (execution == "withheld_pending_confirmation"):
        raise ValueError("user_confirmation_state 'pending' belongs to, and only to, "
                         "'withheld_pending_confirmation' records")

    kinds = list(checkpoint_kinds)
    if isinstance(checkpoint_kinds, str) or any(k not in CHECKPOINT_KINDS for k in kinds) \
            or len(set(kinds)) != len(kinds):
        raise ValueError(f"checkpoint_kinds must be distinct values from {CHECKPOINT_KINDS}, got {checkpoint_kinds!r}")
    if execution == "withheld_pending_confirmation" and not kinds:
        raise ValueError("a 'withheld_pending_confirmation' record must say which checkpoint kind(s) held it")

    if not isinstance(feedforward_returned, bool):
        raise ValueError("feedforward_returned must be a bool")
    if feedforward_returned and execution not in ("executed", "withheld_pending_confirmation"):
        raise ValueError("feedforward is only ever returned with a released answer or a pending-confirmation response")

    if ran:
        if (isinstance(actual_latency_ms, bool) or not isinstance(actual_latency_ms, (int, float))
                or not math.isfinite(actual_latency_ms) or actual_latency_ms < 0):
            raise ValueError("an executed record needs a measured, finite, non-negative actual_latency_ms")
    elif actual_latency_ms is not None:
        raise ValueError(f"actual_latency_ms must be None when Stage 5 did not run (execution={execution!r})")

    esc = _check_escalations(escalations or [])
    if esc and not ran:
        raise ValueError(f"escalations must be empty when nothing ran (execution={execution!r})")

    if stage0_matched_patterns is not None and (
            isinstance(stage0_matched_patterns, str)
            or not all(isinstance(p, str) for p in stage0_matched_patterns)):
        raise ValueError("stage0_matched_patterns must be None or a list of pattern names")
    if stage0_confidence is not None and (isinstance(stage0_confidence, bool)
                                          or not isinstance(stage0_confidence, (int, float))):
        raise ValueError("stage0_confidence must be None or a number")

    decision_dict = asdict(decision)
    entry = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": time.time(),
        "session_id": session_id,
        "request_evidence": evidence,
        "stage0_screen_result": stage0_screen_result,
        "stage0_confidence": stage0_confidence,
        "stage0_matched_patterns": None if stage0_matched_patterns is None else list(stage0_matched_patterns),
        "policy_flags": decision_dict["policy_flags"],
        "session_state_snapshot": session_state_snapshot,
        "alternatives_considered": list(alternatives_considered or []),
        "selected_tier": _enum_value(decision.selected_tier) if ran else None,
        "estimated_cost": decision_dict["cost_estimate"] if ran else None,
        "rationale": decision.rationale,
        "actual_cost": {
            "latency_ms": float(actual_latency_ms) if ran else None,
            "energy_wh": None,      # null until genuinely measured; never a zero placeholder
            "dollars": None,
        },
        "feedforward_returned": feedforward_returned,
        "user_confirmation_state": user_confirmation_state,
        "validation_result": validation_result_from_trace(validation_trace),
        "validation_trace": validation_trace,
        "escalations": esc,
        "human_checkpoint_triggered": bool(kinds),
        "checkpoint_kinds": kinds,
        "final_outcome": FINAL_OUTCOME_BY_EXECUTION[execution],
        "outcome_reason": outcome_reason,
        "execution": execution,
        "withheld_route_estimate": withheld_route_estimate,
        "decision": decision_dict,      # legacy nested snapshot, kept unchanged for now
    }
    line = json.dumps(entry, default=str) + "\n"
    with open(LOG_PATH, "a") as f:
        f.write(line)
