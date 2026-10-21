
"""OI-084: exception descriptions used in logs and stored reasons carry no message text."""
import logging

import pytest

from audit.safe_exc import describe_exception, log_exception, reason_for

CANARY = "CANARY-9f3a-private-request-text"


def _raise_chain():
    try:
        try:
            raise KeyError(CANARY)
        except KeyError as inner:
            raise ValueError(f"wrapped {CANARY}") from inner
    except ValueError as outer:
        return outer


def test_description_has_class_and_site_but_no_message():
    d = describe_exception(_raise_chain())
    assert "ValueError" in d and "KeyError" in d
    assert "test_safe_exc.py" in d and "_raise_chain" in d
    assert CANARY not in d


def test_reason_is_class_name_only():
    assert reason_for(_raise_chain()) == "ValueError"


def test_context_chain_is_also_message_free():
    try:
        try:
            raise OSError(CANARY)
        except OSError:
            raise RuntimeError("second")     # implicit __context__
    except RuntimeError as e:
        d = describe_exception(e)
    assert "OSError" in d and CANARY not in d


def test_cyclic_chain_terminates():
    a, b = ValueError(CANARY), KeyError(CANARY)
    a.__cause__, b.__cause__ = b, a
    assert CANARY not in describe_exception(a)


def test_exception_without_traceback():
    assert CANARY not in describe_exception(ValueError(CANARY))


def test_log_exception_never_writes_message_or_traceback_text(caplog):
    log = logging.getLogger("test.safe_exc")
    with caplog.at_level(logging.DEBUG, logger="test.safe_exc"):
        try:
            raise _raise_chain()
        except ValueError:
            log_exception(log, "stage failed for tier %s", "small")
    assert caplog.records, "nothing was logged"
    for r in caplog.records:
        assert CANARY not in r.getMessage()
        assert CANARY not in caplog.text
        assert r.exc_info is None            # no handler can format a traceback with the message
        assert not r.exc_text
    assert "stage failed for tier small" in caplog.text and "ValueError" in caplog.text


def test_log_exception_outside_except_block_does_not_raise(caplog):
    log = logging.getLogger("test.safe_exc2")
    with caplog.at_level(logging.DEBUG, logger="test.safe_exc2"):
        log_exception(log, "no active exception here")
    assert "no active exception" in caplog.text


def test_describe_never_raises_on_hostile_exception():
    class Hostile(Exception):
        @property
        def __traceback__(self):          # type: ignore[override]
            raise RuntimeError("boom")
    assert isinstance(describe_exception(Hostile(CANARY)), str)
