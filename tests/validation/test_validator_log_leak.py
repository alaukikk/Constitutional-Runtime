
"""OI-084: a validator-level error must not put request or output text into logs or reasons."""
import logging

import validation.validator as v
from policy.schemas import MethodTier, PolicyAction, PolicyFlag, RiskCategory

CANARY = "CANARY-5b88-output-text"


def _boom(text):
    raise RuntimeError(f"cannot check {text!r}")


def _flag(rule_id):
    return PolicyFlag(rule_id=rule_id, risk_category=RiskCategory.DANGEROUS_CONTENT,
                      action=PolicyAction.BLOCK, reason="x")


def test_fail_closed_path(monkeypatch, caplog):
    monkeypatch.setattr(v, "run_non_llm_checks", _boom)
    with caplog.at_level(logging.DEBUG):
        res = v.validate_output(f"req {CANARY}", f"out {CANARY}", MethodTier.SMALL_CLASSIFIER,
                                (_flag("DC-001"),), fail_closed_for=lambda r: True)
    assert res.validator_errored and not res.failed_open
    assert CANARY not in caplog.text and CANARY not in res.reason
    assert "RuntimeError" in caplog.text


def test_fail_open_path(monkeypatch, caplog):
    monkeypatch.setattr(v, "run_non_llm_checks", _boom)
    with caplog.at_level(logging.DEBUG):
        res = v.validate_output(f"req {CANARY}", f"out {CANARY}", MethodTier.SMALL_CLASSIFIER,
                                (), fail_closed_for=lambda r: False)
    assert res.failed_open
    assert CANARY not in caplog.text and CANARY not in res.reason
