
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from policy.schemas import RoutingDecision

LOG_PATH = Path("audit_log.jsonl")

# OI-058: a decision that prevented execution must not look like one that spent
# resources. Every record can say which of these it is.
#
# Sprint 5 (Stage 6 / repair): "executed_withheld" is the state for a request
# whose generation ran (or was attempted) but whose output was NOT released,
# because validation failed, the validator could not complete, or execution
# failed, and no safe repair remained (OI-066). Resources may have been spent,
# so `decision.cost_estimate` is the estimate for the last step that ran, not a
# zero placeholder. It does NOT mean a human reviewed anything.
EXECUTION_STATES = ("executed", "withheld_pending_confirmation", "blocked", "executed_withheld")

# States whose records may carry a validation_trace.
_TRACE_STATES = ("executed", "executed_withheld")


def log_decision(
    session_id: str,
    decision: RoutingDecision,
    *,
    stage0_screen_result: Optional[str] = None,
    session_state_snapshot: Optional[dict] = None,
    execution: Optional[str] = None,
    withheld_route_estimate: Optional[dict] = None,
    validation_trace: Optional[dict] = None,
) -> None:
    """Append-only log of every routing decision made, for later review.

    stage0_screen_result / session_state_snapshot are additive fields toward
    the full Stage 7 audit schema in ARCHITECTURE.md (see the "Audit schema
    rollout" note in EXECUTION_PLAN.md: Sprint 3 adds these two plus estimated
    cost). `decision.cost_estimate`, already logged via asdict below,
    fulfills the schema's `estimated_cost` slot -- no separate field needed.

    OI-058 additions (both optional, so every existing call site keeps working):

    execution -- "executed", "withheld_pending_confirmation", "blocked" or
        "executed_withheld". Disambiguates the zero cost on records where nothing
        ran: for those, `decision.cost_estimate` is a zero placeholder (and
        `selected_tier` is a schema placeholder), NOT measured or incurred spend.
    withheld_route_estimate -- only for "withheld_pending_confirmation": the
        plan's worst-case estimate for the route that was held back, labeled as
        an estimate of something that did not run. Kept separate from
        `decision.cost_estimate` on purpose.

    Sprint 5 addition (optional):

    validation_trace -- only for "executed" / "executed_withheld": a plain dict
        describing Stage 6 and repair for this request (validation failure,
        validator error, whether repair was attempted, its status, the ordered
        events, the final outcome). Toward the Stage 7 schema's
        validation_result / escalations / final_outcome fields. Its shape is
        owned by api/main.py; this module only stores it.

    Audit-write problems fail loud (ARCHITECTURE.md Stage 7 #7), including
    invalid values here.
    """
    if execution is not None and execution not in EXECUTION_STATES:
        raise ValueError(f"execution must be one of {EXECUTION_STATES} or None, got {execution!r}")
    if withheld_route_estimate is not None and execution != "withheld_pending_confirmation":
        raise ValueError("withheld_route_estimate only applies to 'withheld_pending_confirmation' records")
    if validation_trace is not None and execution not in _TRACE_STATES:
        raise ValueError(f"validation_trace only applies to {_TRACE_STATES} records, got execution={execution!r}")
    entry = {
        "timestamp": time.time(),
        "session_id": session_id,
        "decision": asdict(decision),
        "stage0_screen_result": stage0_screen_result,
        "session_state_snapshot": session_state_snapshot,
        "execution": execution,
        "withheld_route_estimate": withheld_route_estimate,
        "validation_trace": validation_trace,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
