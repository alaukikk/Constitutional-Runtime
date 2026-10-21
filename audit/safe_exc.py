
"""Content-free exception descriptions for operational logs and fail-closed reasons (OI-084).

Why this exists: an exception message is free text. ``ValueError(f"bad input {text!r}")``,
``KeyError(user_string)`` or a library error that quotes its input all put request or
model-output text into whatever records the message. ``logging.exception`` and
``logger.warning("... %s", exc)`` do exactly that, and the audit schema's no-request-text
guarantee (CP-001) does not cover application logs.

Rule: operational logs and ``PolicyFlag.reason`` / validator reasons carry only
  * the exception CLASS name (and the class names of its cause/context chain), and
  * the code location of the raise site (file basename, line, function),
never ``str(exc)``, ``exc.args``, ``repr(exc)`` or a formatted traceback (a formatted
traceback includes the message and, for chained exceptions, the cause's message).

Residual limits, stated on purpose:
  * A class NAME can itself be attacker-influenced only if code creates classes from input;
    this repo does not.
  * The logging ``msg``/``args`` the caller passes are the caller's responsibility; callers
    must pass only identifiers (tier, rule id, session id), never request-derived text. The
    static guard in ``tests/audit/test_no_request_text_in_logs.py`` enforces this for
    exception variables, not for every possible argument.
  * Logs may still carry stack-frame source locations. These are code, not content.
"""
from __future__ import annotations

import logging
import os
from types import TracebackType
from typing import Optional

_MAX_CHAIN = 5   # bound the walk; exception chains can be cyclic or long


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    cur: Optional[BaseException] = exc
    while cur is not None and len(seen) < _MAX_CHAIN and all(cur is not s for s in seen):
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


def _raise_site(tb: Optional[TracebackType]) -> str:
    last = None
    n = 0
    while tb is not None and n < 200:
        last, tb, n = tb, tb.tb_next, n + 1
    if last is None:
        return "unknown"
    code = last.tb_frame.f_code
    return f"{os.path.basename(code.co_filename)}:{last.tb_lineno} in {code.co_name}"


def describe_exception(exc: BaseException) -> str:
    """e.g. ``ValueError at engine.py:112 in evaluate (caused by KeyError)``. Never includes
    the exception's message or arguments. Never raises."""
    try:
        chain = _chain(exc)
        names = [type(c).__name__ for c in chain]
        text = f"{names[0]} at {_raise_site(exc.__traceback__)}"
        if len(names) > 1:
            text += " (chain: " + " <- ".join(names[1:]) + ")"
        return text
    except Exception:   # a description helper must not itself break the fail-closed path
        return "exception (details unavailable)"


def reason_for(exc: BaseException) -> str:
    """Short form for stored reasons (``PolicyFlag.reason``): the class name only."""
    try:
        return type(exc).__name__
    except Exception:
        return "exception"


def log_exception(logger: logging.Logger, msg: str, *args: object,
                  exc: Optional[BaseException] = None,
                  level: int = logging.ERROR) -> None:
    """Drop-in replacement for ``logger.exception(msg, *args)`` that never writes the
    exception message or a formatted traceback. Call inside an ``except`` block, or pass
    ``exc``. Never raises."""
    try:
        if exc is None:
            import sys
            exc = sys.exc_info()[1]
        detail = describe_exception(exc) if exc is not None else "no active exception"
        logger.log(level, msg + " [%s]", *args, detail)
    except Exception:
        pass
