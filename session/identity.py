
"""
session/identity.py -- server-issued session identity (OI-013, Sprint 6).

PROBLEM. Stage 2 accumulates risk per session ID. While clients chose their own
ID, any caller could send a fresh ID on every request and never accumulate
anything. This module moves identity to the server: the server mints the session
ID, signs it, and the HTTP layer accepts only tokens it signed.

WHAT THIS FIXES
  * A client can no longer CHOOSE or FORGE a session ID. A token is
    v1.<session_id>.<issued_at>.<signature>, where the signature is an
    HMAC-SHA256 over the first three parts with a server-side secret, compared in
    constant time. Changing any part invalidates it.
  * The session ID inside the token is 144 bits of server-generated randomness,
    so IDs are neither guessable nor client-influenced.
  * Confirmation tokens (interface/human_checkpoint.py) are bound to this ID, so
    they can no longer be bound to an ID the client invented.

WHAT IT DOES NOT FIX (stated limits, tracked as OI-078; do not oversell)
  * A client can still ASK for a new session. Issuance is bounded only by a
    per-client rate limit (default 10 per hour), keyed on a hash of the peer
    address. So the reset path is narrowed to "at most N fresh sessions per
    window per client key", not eliminated. A real fix needs user identity
    (accounts), which is out of scope.
  * The client key is weak identity: shared addresses (NAT) are throttled
    together, and an attacker with many addresses is not throttled at all. Proxy
    headers are deliberately NOT trusted.
  * It proves possession of a token the server issued, not who the human is.
    OI-040 (human identity behind a confirmation) remains open.
  * State is per process and in memory (OI-020/OI-041): a restart or a second
    worker starts a fresh limiter, and with an ephemeral secret old tokens stop
    verifying (which also resets session state, since that is in memory too).
  * Expiry (default 7 days) means a session eventually ends and a new one starts
    clean. That is inherent to any expiring identity and is a placeholder (OI-078).

Failure behavior: everything here fails CLOSED. A malformed, forged, expired or
unverifiable token is rejected; an error while issuing refuses issuance; a full
limiter table refuses issuance rather than evicting live entries (evicting would
hand clients a free reset). Nothing in this module uses AI.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

TOKEN_VERSION = "v1"
_SESSION_ID_BYTES = 18            # 144 bits
_MAX_TOKEN_LEN = 256              # reject absurd input before any work
_CLOCK_SKEW_SECONDS = 60          # tolerated "issued in the future" drift
_MAX_TRACKED_CLIENTS = 10_000     # limiter table bound; full -> refuse, never evict live entries

# Verification failure reasons (stable codes for logs/tests; never shown with detail to callers).
INVALID = "invalid"
EXPIRED = "expired"


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session_id: str
    expires_at: int            # epoch seconds


@dataclass(frozen=True)
class IssuanceResult:
    ok: bool
    session: Optional[IssuedSession] = None
    reason: Optional[str] = None       # "rate_limited" | "issuer_busy" | "issuance_error"


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    session_id: Optional[str] = None
    reason: Optional[str] = None       # INVALID | EXPIRED


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class SessionIdentity:
    def __init__(
        self,
        secret: Optional[str] = None,
        *,
        ttl_seconds: int = 604_800,
        issue_limit: int = 10,
        issue_window_seconds: int = 3_600,
        max_tracked_clients: int = _MAX_TRACKED_CLIENTS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        for name, value in (("ttl_seconds", ttl_seconds), ("issue_limit", issue_limit),
                            ("issue_window_seconds", issue_window_seconds),
                            ("max_tracked_clients", max_tracked_clients)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")
        if secret is None or secret == "":
            log.warning("no SESSION_SECRET configured: using a random per-process secret; "
                        "issued sessions will not survive a restart")
            secret = secrets.token_urlsafe(32)
        if not isinstance(secret, str):
            raise TypeError("secret must be a string")
        self._key = secret.encode("utf-8")
        self._ttl = ttl_seconds
        self._limit = issue_limit
        self._window = issue_window_seconds
        self._max_clients = max_tracked_clients
        self._clock = clock
        self._issued: dict[str, deque] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ signing

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode("utf-8"), hashlib.sha256).digest())

    def client_key(self, raw_peer: str) -> str:
        """Hash a peer address so the limiter never stores raw addresses."""
        return _b64(hmac.new(self._key, b"client:" + str(raw_peer).encode("utf-8"),
                             hashlib.sha256).digest())[:32]

    # ------------------------------------------------------------------ issuing

    def issue(self, client_key: str) -> IssuanceResult:
        """Mint a new session for `client_key`, or refuse. Never raises."""
        try:
            if not isinstance(client_key, str) or not client_key:
                return IssuanceResult(False, reason="issuance_error")
            now = self._clock()
            with self._lock:
                stamps = self._issued.get(client_key)
                if stamps is None:
                    if len(self._issued) >= self._max_clients:
                        self._purge_expired(now)
                    if len(self._issued) >= self._max_clients:
                        # Evicting a live entry would give that client a free reset.
                        return IssuanceResult(False, reason="issuer_busy")
                    stamps = self._issued[client_key] = deque()
                while stamps and now - stamps[0] >= self._window:
                    stamps.popleft()
                if len(stamps) >= self._limit:
                    return IssuanceResult(False, reason="rate_limited")
                stamps.append(now)

            sid = secrets.token_urlsafe(_SESSION_ID_BYTES)
            issued_at = int(now)
            body = f"{TOKEN_VERSION}.{sid}.{issued_at}"
            token = f"{body}.{self._sign(body)}"
            return IssuanceResult(True, IssuedSession(token, sid, issued_at + self._ttl))
        except Exception:
            log.exception("session issuance failed; refusing")
            return IssuanceResult(False, reason="issuance_error")

    def _purge_expired(self, now: float) -> None:
        dead = [k for k, d in self._issued.items() if not d or now - d[-1] >= self._window]
        for k in dead:
            del self._issued[k]

    # ------------------------------------------------------------------ verifying

    def verify(self, token: object) -> VerifyResult:
        """Check a presented token. Never raises; any problem is a rejection."""
        try:
            if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LEN:
                return VerifyResult(False, reason=INVALID)
            parts = token.split(".")
            if len(parts) != 4 or parts[0] != TOKEN_VERSION:
                return VerifyResult(False, reason=INVALID)
            _, sid, issued_raw, sig = parts
            if not sid or not sig or not issued_raw.isdigit():
                return VerifyResult(False, reason=INVALID)
            body = f"{TOKEN_VERSION}.{sid}.{issued_raw}"
            if not hmac.compare_digest(sig.encode("utf-8"), self._sign(body).encode("utf-8")):
                return VerifyResult(False, reason=INVALID)
            issued_at, now = int(issued_raw), self._clock()
            if issued_at > now + _CLOCK_SKEW_SECONDS:
                return VerifyResult(False, reason=INVALID)
            if now >= issued_at + self._ttl:
                return VerifyResult(False, reason=EXPIRED)
            return VerifyResult(True, session_id=sid)
        except Exception:
            log.exception("session verification failed; rejecting")
            return VerifyResult(False, reason=INVALID)
