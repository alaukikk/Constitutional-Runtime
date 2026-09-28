
"""Stage 2 — Session Context.

Tracks cumulative risk / cost / turn count per session and derives extra
constraints for the current turn.

Core rule (ARCHITECTURE.md): session context may only TIGHTEN. Nothing in
this module can lower a Stage 0/1 decision; it only supplies a *floor*
(`min_action`) that the router must apply on top of them, and that floor
is a ratchet -- once raised for a session it never comes back down.

No AI, no judgment calls: running totals and thresholds only.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field, replace
from typing import Optional, Protocol

from policy.schemas import PolicyAction, PolicyFlag

log = logging.getLogger(__name__)

# Severity ordering, used to compare/ratchet floors.
ACTION_ORDER = {
    PolicyAction.ALLOW: 0,
    PolicyAction.FLAG: 1,
    PolicyAction.REQUIRE_HUMAN: 2,
    PolicyAction.BLOCK: 3,
}

# Risk points each policy flag / Stage 0 verdict contributes to the session.
ACTION_RISK_POINTS = {
    PolicyAction.ALLOW: 0.0,
    PolicyAction.FLAG: 1.0,
    PolicyAction.REQUIRE_HUMAN: 3.0,
    PolicyAction.BLOCK: 5.0,
}
VERDICT_RISK_POINTS = {"clean": 0.0, "suspicious": 2.0, "blocked": 5.0}
UNKNOWN_VERDICT_POINTS = 2.0    # unrecognised verdict -> treat as suspicious
INVALID_INPUT_POINTS = 1.0      # malformed cost etc. is itself a signal

# Requests with no usable session id share ONE bucket, so omitting the id
# is never a way to get a fresh, clean session.
ANONYMOUS_SESSION = "__anonymous__"


@dataclass(frozen=True)
class SessionConfig:
    require_human_risk: float = 4.0    # cumulative risk >= this -> human checkpoint
    block_risk: float = 12.0           # cumulative risk >= this -> block
    require_human_cost: float = 1.0    # cumulative dollars >= this -> human checkpoint


@dataclass
class SessionState:
    session_id: str
    turn_count: int = 0
    cumulative_risk: float = 0.0
    cumulative_cost: float = 0.0       # dollars
    invalid_inputs: int = 0
    floor: PolicyAction = PolicyAction.ALLOW   # ratchet: only ever rises

    def snapshot(self) -> dict:
        """Plain dict for the per-turn audit record (Stage 2, req. 9)."""
        return {
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "cumulative_risk": self.cumulative_risk,
            "cumulative_cost": self.cumulative_cost,
            "invalid_inputs": self.invalid_inputs,
            "floor": self.floor.value,
        }


@dataclass(frozen=True)
class SessionConstraints:
    """What this turn must carry on top of the Stage 0/1 result."""
    min_action: PolicyAction = PolicyAction.ALLOW
    reasons: tuple[str, ...] = ()


class SessionStore(Protocol):
    """Swap-in point for Redis/DB later. Must return/accept copies."""
    def get(self, session_id: str) -> Optional[SessionState]: ...
    def put(self, state: SessionState) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}

    def get(self, session_id: str) -> Optional[SessionState]:
        s = self._data.get(session_id)
        return replace(s) if s else None

    def put(self, state: SessionState) -> None:
        self._data[state.session_id] = replace(state)


def _normalize_id(session_id: object) -> str:
    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()
    return ANONYMOUS_SESSION


def _safe_cost(value: object) -> Optional[float]:
    """Return a usable non-negative cost, or None if it is malformed."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


class SessionManager:
    def __init__(self, store: Optional[SessionStore] = None,
                 config: Optional[SessionConfig] = None) -> None:
        self._store = store if store is not None else InMemoryStore()
        self._cfg = config or SessionConfig()
        # One lock around the whole read-modify-write: without it, two
        # concurrent turns could overwrite each other and lose risk points.
        self._lock = threading.Lock()

    def record_turn(
        self,
        session_id: object,
        flags: list[PolicyFlag],
        stage0_verdict: str = "clean",
        turn_cost: float = 0.0,
    ) -> tuple[SessionState, SessionConstraints]:
        """Fold this turn into the session; return (state copy, constraints).

        Call this for EVERY turn, including ones Stage 0/1 blocked --
        blocked probes are exactly what should accumulate.
        """
        sid = _normalize_id(session_id)
        with self._lock:
            read_ok = True
            try:
                state = self._store.get(sid)
            except Exception:
                # Spec: fail open on read errors (fresh session) but log it.
                log.exception("session read failed for %s; using fresh state", sid)
                state, read_ok = None, False
            if state is None:
                state = SessionState(session_id=sid)

            state.turn_count += 1

            risk = VERDICT_RISK_POINTS.get(
                str(stage0_verdict).lower(), UNKNOWN_VERDICT_POINTS)
            risk += sum(ACTION_RISK_POINTS[f.action] for f in flags)

            cost = _safe_cost(turn_cost)
            if cost is None:
                state.invalid_inputs += 1
                risk += INVALID_INPUT_POINTS
                cost = 0.0
            state.cumulative_risk += risk
            state.cumulative_cost += cost

            constraints = self._derive(state)
            if ACTION_ORDER[constraints.min_action] > ACTION_ORDER[state.floor]:
                state.floor = constraints.min_action
            else:  # ratchet: never below the floor already reached
                constraints = SessionConstraints(state.floor, constraints.reasons
                                                 or ("session floor previously raised",))

            log.info("session snapshot: %s", state.snapshot())

            # If the read failed, the stored history is intact but unseen;
            # writing our fresh state would clobber it. Skip the write.
            if read_ok:
                try:
                    self._store.put(state)
                except Exception:
                    log.exception("session write failed for %s", sid)
            return replace(state), constraints

    def _derive(self, s: SessionState) -> SessionConstraints:
        action, reasons = PolicyAction.ALLOW, []
        if s.cumulative_risk >= self._cfg.block_risk:
            action = PolicyAction.BLOCK
            reasons.append(f"cumulative risk {s.cumulative_risk:g} >= {self._cfg.block_risk:g}")
        elif s.cumulative_risk >= self._cfg.require_human_risk:
            action = PolicyAction.REQUIRE_HUMAN
            reasons.append(f"cumulative risk {s.cumulative_risk:g} >= {self._cfg.require_human_risk:g}")
        if s.cumulative_cost >= self._cfg.require_human_cost:
            if ACTION_ORDER[PolicyAction.REQUIRE_HUMAN] > ACTION_ORDER[action]:
                action = PolicyAction.REQUIRE_HUMAN
            reasons.append(f"cumulative cost ${s.cumulative_cost:g} >= ${self._cfg.require_human_cost:g}")
        return SessionConstraints(action, tuple(reasons))
