
"""
interface/human_checkpoint.py -- the human confirmation gate for REQUIRE_HUMAN.

Satisfies ARCHITECTURE.md Stage 1 #10 ("Stage 4/7 must enforce a human
checkpoint before or after execution") with a confirm-BEFORE-execute flow:

  1. A request that needs a human is NOT executed. The caller gets a
     "needs confirmation" result carrying a token from issue().
  2. To proceed, the caller re-submits the SAME request with that token.
     The re-submission runs Stage 0, 1 and 2 again from scratch; the token
     only satisfies the human-checkpoint requirement. It is never examined
     for a Stage 0/Stage 1/session BLOCK and can never override one.

Token properties (each one closes a specific bypass):
  * HMAC-SHA256 signed           -> cannot be forged or edited (exp, nonce).
  * Bound to session id          -> cannot be carried to another session.
  * Bound to the SHA-256 of the exact normalized text -> cannot confirm a
    different message ("confirm A, execute B").
  * Bound to the exact set of rule ids that triggered it -> cannot confirm
    a request that now trips different rules.
  * Expires (ttl_seconds)        -> a stale approval cannot be used later.
  * Single use (spent-nonce set, checked and set atomically under a lock)
    -> cannot be replayed, including by concurrent requests.
  * Verification and consumption are ONE step, so a replay race cannot let
    two requests both pass.
  * Any internal error counts as "not confirmed" (fail closed).
  * Issuance is stateless, so spamming REQUIRE_HUMAN requests cannot grow
    memory; only successful consumptions are remembered, and only until the
    token would have expired anyway.

What this does NOT prove (tracked in OPEN_ENDS): that a *human* made the
second call. It proves an explicit, content-bound second call. Closing that
gap needs an authenticated channel upstream of this function (same boundary
as OI-013), which does not exist in this repo.

The secret: pass one in (api/settings.py CHECKPOINT_SECRET). If none is
given a random per-process secret is generated, so tokens die on restart and
are not valid across workers -- safe (fail closed), just inconvenient.
Secrets shorter than 16 bytes are rejected at construction.

No AI, no judgment: hashing and set membership only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import numbers
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300
MAX_TOKEN_CHARS = 512
MAX_SPENT_ENTRIES = 100_000
MIN_SECRET_BYTES = 16
_DOMAIN = b"constitutional-runtime/human-checkpoint/v1|"


@dataclass(frozen=True)
class Confirmation:
    """Result of checking a token. `nonce` is a short id safe to audit-log;
    the token itself is a bearer credential and must never be logged."""
    ok: bool
    reason: str
    nonce: Optional[str] = None


class CheckpointManager:
    def __init__(
        self,
        secret=None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        now: Callable[[], float] = time.time,
        max_spent: int = MAX_SPENT_ENTRIES,
    ) -> None:
        if secret is None or secret == "" or secret == b"":
            self._secret = secrets.token_bytes(32)
            self.secret_is_ephemeral = True
        else:
            if isinstance(secret, str):
                raw = secret.encode("utf-8")
            elif isinstance(secret, (bytes, bytearray)):
                raw = bytes(secret)
            else:
                raise TypeError("secret must be str, bytes or None")
            if len(raw) < MIN_SECRET_BYTES:
                raise ValueError(f"checkpoint secret must be at least {MIN_SECRET_BYTES} bytes")
            self._secret = raw
            self.secret_is_ephemeral = False

        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, numbers.Real):
            raise TypeError("ttl_seconds must be a real number")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and > 0")
        if isinstance(max_spent, bool) or not isinstance(max_spent, int) or max_spent <= 0:
            raise ValueError("max_spent must be a positive int")

        self._ttl = float(ttl_seconds)
        self._now = now
        self._max_spent = max_spent
        self._spent: dict[str, int] = {}     # nonce -> expiry
        self._lock = threading.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    # ---- signing ----------------------------------------------------------
    def _mac(self, nonce: str, exp: int, session_id: str, text: str,
             rule_ids: Iterable[str]) -> str:
        text_hash = hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()
        # JSON gives an unambiguous encoding: no delimiter-injection between fields.
        material = json.dumps(
            ["v1", nonce, exp, session_id, text_hash, sorted({str(r) for r in rule_ids})],
            separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hmac.new(self._secret, _DOMAIN + material, hashlib.sha256).hexdigest()

    # ---- issue ------------------------------------------------------------
    def issue(self, session_id: str, text: str, rule_ids: Iterable[str]) -> str:
        if not isinstance(session_id, str) or not isinstance(text, str):
            raise TypeError("session_id and text must be str")
        nonce = secrets.token_hex(16)
        exp = int(self._now() + self._ttl)
        return f"{nonce}.{exp}.{self._mac(nonce, exp, session_id, text, rule_ids)}"

    # ---- verify + consume (one atomic step) -------------------------------
    def verify_and_consume(self, token, session_id, text, rule_ids) -> Confirmation:
        try:
            return self._verify_and_consume(token, session_id, text, rule_ids)
        except Exception:
            log.exception("checkpoint verification errored; treating as NOT confirmed")
            return Confirmation(False, "verification_error")

    def _verify_and_consume(self, token, session_id, text, rule_ids) -> Confirmation:
        if (not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS
                or not isinstance(session_id, str) or not isinstance(text, str)):
            return Confirmation(False, "malformed")
        parts = token.split(".")
        if len(parts) != 3:
            return Confirmation(False, "malformed")
        nonce, exp_s, mac = parts
        if not nonce or not exp_s or not exp_s.isascii() or not exp_s.isdigit():
            return Confirmation(False, "malformed")
        exp = int(exp_s)

        expected = self._mac(nonce, exp, session_id, text, rule_ids)
        if not hmac.compare_digest(mac.encode("utf-8", "replace"), expected.encode("ascii")):
            return Confirmation(False, "bad_signature")

        now = self._now()
        if exp < now:
            return Confirmation(False, "expired")

        short = nonce[:8]
        with self._lock:
            for n in [n for n, e in self._spent.items() if e < now]:
                del self._spent[n]                # expired tokens fail anyway
            if nonce in self._spent:
                return Confirmation(False, "replayed", short)
            if len(self._spent) >= self._max_spent:
                return Confirmation(False, "store_full", short)   # fail closed
            self._spent[nonce] = exp
        return Confirmation(True, "confirmed", short)


def confirmation_message(reasons: Sequence[str], ttl_seconds: float) -> str:
    """User-facing text for a needs-confirmation result (no token in it)."""
    why = "; ".join(r for r in reasons if r) or "this request requires human review"
    minutes = max(1, round(ttl_seconds / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (f"This request needs human confirmation before it is answered ({why}). "
            f"If you confirm it, re-submit the same request with the confirmation_token "
            f"from this response within {minutes} {unit}.")
