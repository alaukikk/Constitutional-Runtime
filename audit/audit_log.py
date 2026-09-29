
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from policy.schemas import RoutingDecision

LOG_PATH = Path("audit_log.jsonl")


def log_decision(
    session_id: str,
    decision: RoutingDecision,
    *,
    stage0_screen_result: Optional[str] = None,
    session_state_snapshot: Optional[dict] = None,
) -> None:
    """Append-only log of every routing decision made, for later review.

    stage0_screen_result / session_state_snapshot are additive fields toward
    the full Stage 7 audit schema in ARCHITECTURE.md (see the "Audit schema
    rollout" note in EXECUTION_PLAN.md: Sprint 3 adds these two plus estimated
    cost). Both default to None so every existing call site keeps working
    unchanged. `decision.cost_estimate`, already logged via asdict below,
    fulfills the schema's `estimated_cost` slot -- no separate field needed.
    """
    entry = {
        "timestamp": time.time(),
        "session_id": session_id,
        "decision": asdict(decision),
        "stage0_screen_result": stage0_screen_result,
        "session_state_snapshot": session_state_snapshot,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
