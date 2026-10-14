
"""Shared helpers for tests that call audit.audit_log.log_decision directly (schema v2)."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from audit import audit_log
from audit.request_evidence import NOT_TEXT_INPUT, build_request_evidence
from policy.schemas import MethodTier, RoutingDecision, TierCostEstimate


def no_text_evidence() -> dict:
    return build_request_evidence(None, normalization_version=None, status=NOT_TEXT_INPUT)


def cache_decision() -> RoutingDecision:
    """The OI-058 placeholder decision used on records where nothing ran."""
    return RoutingDecision(MethodTier.CACHE, None, "r", TierCostEstimate(tier=MethodTier.CACHE))


def llm_decision() -> RoutingDecision:
    return RoutingDecision(MethodTier.LLM_LOW_REASONING, "m", "r",
                           TierCostEstimate(MethodTier.LLM_LOW_REASONING, "m", 0.01, 100.0, 0.5))


def v2_kwargs(execution: str = "blocked", **over) -> dict:
    """The smallest valid keyword set for each execution state; `over` overrides any of it."""
    kw = {"execution": execution, "request_evidence": no_text_evidence(), "outcome_reason": "policy_gate"}
    if execution == "executed":
        kw.update(outcome_reason=None, actual_latency_ms=1.0)
    elif execution == "executed_withheld":
        kw.update(outcome_reason="output_withheld_validation_failed", actual_latency_ms=1.0)
    elif execution == "withheld_pending_confirmation":
        kw.update(outcome_reason="human_confirmation_required", user_confirmation_state="pending",
                  checkpoint_kinds=["human_required"])
    kw.update(over)
    return kw


def write_record(decision=None, session_id="s1", **kwargs) -> dict:
    """Write one record to a temp log and return it parsed. `kwargs` go to log_decision as-is."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "l.jsonl"
        with mock.patch.object(audit_log, "LOG_PATH", path):
            audit_log.log_decision(session_id, decision or cache_decision(), **kwargs)
        return json.loads(path.read_text().strip().splitlines()[-1])
