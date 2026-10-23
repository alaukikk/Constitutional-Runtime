

"""
Stage 3/5 deterministic tier — real implementation. Calculator + simple
static fact lookup, no AI.

Security note: deliberately does NOT use eval() or any other code-execution
mechanism to handle arithmetic. A strict regex only matches a single
`number operator number` shape; anything else (including text crafted to
look like a Python expression) simply doesn't match and falls through to a
costlier tier. Safe by construction, not by attempted sanitization.

Conservative by design: this tier should only ever answer when it can do so
RELIABLY (ARCHITECTURE.md Stage 3 #1 -- "the cheapest tier that can reliably
handle it"). Anything ambiguous, multi-step, or outside the narrow patterns
below returns None rather than guessing.
"""
from __future__ import annotations
import math
import re
from decimal import Context, Decimal, InvalidOperation
from typing import Optional

# Optional lead-in words. A bare expression and the same expression behind one of these mean the same
# thing, so both are answered; anything else around the expression (extra words, a second operation)
# fails the full-match and falls through to a costlier tier.
_LEAD = r"^\s*(?:(?:please\s+)?(?:calculate|compute|evaluate|what\s+is|what's|how\s+much\s+is)\s+)?"
_NUM = r"(-?\d{1,15}(?:\.\d{1,15})?)"
_TAIL = r"\s*\??\s*$"

# Single binary operation only, e.g. "2 + 2", "10 / 4". Deliberately does NOT
# support chained operations (e.g. "2 + 2 * 3") -- operator precedence bugs
# are an easy way for a "deterministic" tier to silently give a wrong answer.
_ARITHMETIC_RE = re.compile(_LEAD + _NUM + r"\s*([+\-*/])\s*" + _NUM + _TAIL, re.IGNORECASE)
_PERCENT_RE = re.compile(_LEAD + _NUM + r"\s*%\s*of\s+" + _NUM + _TAIL, re.IGNORECASE)
_SQUARED_RE = re.compile(_LEAD + _NUM + r"\s+squared" + _TAIL, re.IGNORECASE)
_SQRT_RE = re.compile(_LEAD + r"the\s+square\s+root\s+of\s+(\d{1,15})" + _TAIL, re.IGNORECASE)

# Exactness rule ("reliable", ARCHITECTURE.md Stage 3 #1): operands are capped at 15 digits so every
# +, -, * result fits the 50-digit context EXACTLY. A quotient is answered only when it is exact
# (terminating); 1/3 falls through instead of being answered with an arbitrary rounding. Decimal
# arithmetic is used so 0.1 + 0.2 is 0.3, not 0.30000000000000004.
_CTX = Context(prec=50)

_STATIC_FACTS = {
    "what is the capital of france": "Paris",
    "what is the capital of japan": "Tokyo",
    "how many days are in a week": "7",
    "how many months are in a year": "12",
}


def _fmt(d: Decimal) -> str:
    out = format(d.normalize(), "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


def _exact(d: Decimal) -> bool:
    return d.is_finite() and len(d.as_tuple().digits) <= 40


def _try_arithmetic(text: str) -> Optional[str]:
    match = _ARITHMETIC_RE.match(text)
    if not match:
        return None
    left, op, right = match.groups()
    a, b = Decimal(left), Decimal(right)
    if op == "+":
        result = _CTX.add(a, b)
    elif op == "-":
        result = _CTX.subtract(a, b)
    elif op == "*":
        result = _CTX.multiply(a, b)
    else:
        if b == 0:
            return None  # fall through rather than crash or claim an answer
        result = _CTX.divide(a, b)
        if _CTX.multiply(result, b) != a:
            return None  # non-terminating quotient: not answerable without choosing a rounding
    return _fmt(result) if _exact(result) else None


def _try_percent(text: str) -> Optional[str]:
    match = _PERCENT_RE.match(text)
    if not match:
        return None
    pct, base = Decimal(match.group(1)), Decimal(match.group(2))
    result = _CTX.divide(_CTX.multiply(pct, base), Decimal(100))   # x*y/100 is always terminating
    return _fmt(result) if _exact(result) else None


def _try_squared(text: str) -> Optional[str]:
    match = _SQUARED_RE.match(text)
    if not match:
        return None
    n = Decimal(match.group(1))
    return _fmt(_CTX.multiply(n, n))


def _try_sqrt(text: str) -> Optional[str]:
    match = _SQRT_RE.match(text)
    if not match:
        return None
    n = int(match.group(1))
    r = math.isqrt(n)
    return str(r) if r * r == n else None      # perfect squares only; irrational roots fall through


def try_deterministic(request_text: str) -> Optional[str]:
    text = (request_text or "").strip()
    if not text:
        return None
    for attempt in (_try_arithmetic, _try_percent, _try_squared, _try_sqrt):
        answer = attempt(text)
        if answer is not None:
            return answer
    return _STATIC_FACTS.get(text.lower().rstrip("?").strip())
