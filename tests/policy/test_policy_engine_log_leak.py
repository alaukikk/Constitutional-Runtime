
"""OI-084: a rule error must not copy request text into logs or PolicyFlag.reason."""
import copy
import logging

import pytest

from guardrails.match_view import build_match_views
from policy.engine import PolicyEngine
from policy.schemas import PolicyAction

CANARY = "CANARY-7c21-request-text"


def _all_text(flags):
    return " | ".join(f"{f.rule_id} {f.reason}" for f in flags)


def _engine_with_view_error(monkeypatch):
    engine = PolicyEngine()

    def boom(rule, texts):
        try:
            raise KeyError(texts[0])                  # the exception quotes the request text
        except KeyError as inner:
            raise ValueError(f"bad view for {texts[0]!r}") from inner
    monkeypatch.setattr(engine, "_view_match", boom)
    return engine


def test_fail_closed_reason_and_logs_carry_no_request_text(monkeypatch, caplog):
    engine = _engine_with_view_error(monkeypatch)
    text = f"harmless {CANARY} words"
    with caplog.at_level(logging.DEBUG):
        flags, action = engine.evaluate(text, match_views=build_match_views(text))
    assert action == PolicyAction.BLOCK                 # fail-closed behaviour unchanged
    assert flags and all("failed closed" in f.reason for f in flags)
    assert CANARY not in _all_text(flags)
    assert CANARY not in caplog.text
    assert "ValueError" in flags[0].reason               # the class name is still informative


def test_fail_open_log_carries_no_request_text(monkeypatch, caplog):
    engine = _engine_with_view_error(monkeypatch)
    engine._fail_closed_for = lambda rule_id: False      # every rule fail-open
    text = f"harmless {CANARY} words"
    with caplog.at_level(logging.DEBUG):
        flags, action = engine.evaluate(text, match_views=build_match_views(text))
    assert action == PolicyAction.ALLOW and flags == []
    assert "FAIL-OPEN" in caplog.text.upper() or "fail-open" in caplog.text
    assert CANARY not in caplog.text


def test_keyword_type_error_message_is_not_stored():
    engine = PolicyEngine()
    rules = copy.deepcopy(engine._rules)
    for r in rules:
        if r["rule_id"] == "DC-001":
            r["keywords"] = None
    engine._rules = rules
    flags, _ = engine.evaluate(f"text {CANARY}")
    dc = next(f for f in flags if f.rule_id == "DC-001")
    assert "TypeError" in dc.reason and CANARY not in dc.reason
