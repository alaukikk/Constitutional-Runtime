
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from policy.schemas import RoutingDecision

LOG_PATH = Path("audit_log.jsonl")

# OI-058: a decision that prevented execution must not look like one that spent
# resources. Every record can say which of these it is.
EXECUTION_STATES = ("executed", "withheld_pending_confirmation", "blocked")


def log_decision(
    session_id: str,
    decision: RoutingDecision,
    *,
    stage0_screen_result: Optional[str] = None,
    session_state_snapshot: Optional[dict] = None,
    execution: Optional[str] = None,
    withheld_route_estimate: Optional[dict] = None,
) -> None:
    """Append-only log of every routing decision made, for later review.

    stage0_screen_result / session_state_snapshot are additive fields toward
    the full Stage 7 audit schema in ARCHITECTURE.md (see the "Audit schema
    rollout" note in EXECUTION_PLAN.md: Sprint 3 adds these two plus estimated
    cost). `decision.cost_estimate`, already logged via asdict below,
    fulfills the schema's `estimated_cost` slot -- no separate field needed.

    OI-058 additions (both optional, so every existing call site keeps working):

    execution -- "executed", "withheld_pending_confirmation" or "blocked".
        Disambiguates the zero cost on records where nothing ran: for those,
        `decision.cost_estimate` is a zero placeholder (and `selected_tier` is a
        schema placeholder), NOT measured or incurred spend.
    withheld_route_estimate -- only for "withheld_pending_confirmation": the
        plan's worst-case estimate for the route that was held back, labeled as
        an estimate of something that did not run. Kept separate from
        `decision.cost_estimate` on purpose.

    Audit-write problems fail loud (ARCHITECTURE.md Stage 7 #7), including
    invalid values here.
    """
    if execution is not None and execution not in EXECUTION_STATES:
        raise ValueError(f"execution must be one of {EXECUTION_STATES} or None, got {execution!r}")
    if withheld_route_estimate is not None and execution != "withheld_pending_confirmation":
        raise ValueError("withheld_route_estimate only applies to 'withheld_pending_confirmation' records")
    entry = {
        "timestamp": time.time(),
        "session_id": session_id,
        "decision": asdict(decision),
        "stage0_screen_result": stage0_screen_result,
        "session_state_snapshot": session_state_snapshot,
        "execution": execution,
        "withheld_route_estimate": withheld_route_estimate,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
