
"""OI-084: through real stage code, an exception that quotes request text must not reach logs."""
import logging

import tiers.small_classifier as sc
from interface.human_checkpoint import CheckpointManager
from session.session_state import SessionManager
from triage.decision import plan_request

CANARY = "CANARY-2d40-request-text"


def _quoting_error(*a, **k):
    text = a[0] if a else CANARY
    try:
        raise KeyError(str(text))
    except KeyError as inner:
        raise ValueError(f"cannot handle {text!r}") from inner


def test_small_classifier_failure(monkeypatch, caplog):
    monkeypatch.setattr(sc, "extract_message", _quoting_error)
    with caplog.at_level(logging.DEBUG):
        assert sc.try_small_classifier(f"classify {CANARY}") is None
    assert "ValueError" in caplog.text and CANARY not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_triage_classifier_failure(caplog):
    with caplog.at_level(logging.DEBUG):
        plan = plan_request(f"hello {CANARY}", classifier=_quoting_error)
    assert plan is not None
    assert "ValueError" in caplog.text and CANARY not in caplog.text


def test_checkpoint_verification_failure(monkeypatch, caplog):
    mgr = CheckpointManager(secret="s" * 32)
    monkeypatch.setattr(mgr, "_verify_and_consume", _quoting_error)
    with caplog.at_level(logging.DEBUG):
        res = mgr.verify_and_consume("tok", "sid", f"text {CANARY}", ["HAC-001"])
    assert res.ok is False
    assert CANARY not in caplog.text


class _ExplodingStore:
    def get(self, session_id):
        _quoting_error(CANARY)

    def put(self, state):
        _quoting_error(CANARY)


def test_session_store_failures(caplog):
    mgr = SessionManager(store=_ExplodingStore())
    with caplog.at_level(logging.DEBUG):
        state, constraints = mgr.record_turn("a" * 20, [])
    assert state.turn_count == 1
    assert "ValueError" in caplog.text and CANARY not in caplog.text
