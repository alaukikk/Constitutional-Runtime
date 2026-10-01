
import json

import pytest

import api.main as main_module
import interface.feedforward as ff
import tiers.cache_lookup as cache_lookup
from api.main import process_request
from interface.human_checkpoint import CheckpointManager
from session.session_state import SessionManager

SECRET = "k" * 32
LEGAL = "I need legal advice about my lease"       # trips HAC-001 (REQUIRE_HUMAN)
BENIGN = "Tell me an interesting fact about octopuses"


class FakeRedis:
    def __init__(self):
        self.store = {}
    def ping(self): return True
    def get(self, key): return self.store.get(key)
    def set(self, key, value, ex=None): self.store[key] = value


class Env:
    def __init__(self, log_path):
        self.log_path = log_path

    def last(self):
        return json.loads(self.log_path.read_text().splitlines()[-1])


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache_lookup.configure_client(FakeRedis())
    monkeypatch.setattr(main_module, "_session_manager", SessionManager())
    monkeypatch.setattr(main_module, "_checkpoint", CheckpointManager(secret=SECRET))
    yield Env(tmp_path / "audit_log.jsonl")
    cache_lookup._client = None


@pytest.fixture
def gate_on(monkeypatch):
    """Make every plan look expensive so the Stage 4 cost gate fires."""
    monkeypatch.setattr(main_module, "evaluate_gate",
                        lambda plan: ff.evaluate_gate(plan, high_cost_wh=1e-9, high_cost_usd=1e-9))


# ---- feedforward text on the normal path ----

def test_answered_response_carries_the_outcome_and_the_audit_says_so(env):
    r = process_request("2 + 2", session_id="f1")
    assert r.blocked is False
    assert r.feedforward.startswith("Answered by: rule-based solver")
    assert env.last()["decision"]["rationale"].endswith("Feedforward attached to response.")


def test_ordinary_requests_are_not_gated(env):
    r = process_request(BENIGN, session_id="f2")
    assert r.blocked is False and r.needs_confirmation is False


def test_needs_confirmation_response_shows_the_route_before_execution(env):
    r = process_request(LEGAL, session_id="f3")
    assert r.needs_confirmation
    assert "Planned route" in r.response
    assert r.feedforward and "Planned route" in r.feedforward
    assert "Feedforward shown before execution" in env.last()["decision"]["rationale"]


# ---- failure behavior ----

def test_render_failure_fails_open_for_ordinary_requests(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("template bug")

    monkeypatch.setattr(ff, "outcome_text", boom)
    r = process_request(BENIGN, session_id="f4")
    assert r.blocked is False and r.feedforward is None
    assert env.last()["decision"]["rationale"].endswith("Feedforward unavailable (render error).")


def test_render_failure_never_removes_the_require_human_gate(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("template bug")

    monkeypatch.setattr(ff, "preview_text", boom)
    r = process_request(LEGAL, session_id="f5")
    assert r.blocked and r.needs_confirmation and r.confirmation_token
    assert r.feedforward is None
    assert "Feedforward unavailable" in env.last()["decision"]["rationale"]


def test_gate_evaluation_error_fails_closed(env, monkeypatch):
    def boom(plan):
        raise RuntimeError("estimator exploded")

    monkeypatch.setattr(ff, "worst_case", boom)
    r = process_request(BENIGN, session_id="f6")
    assert r.blocked and r.needs_confirmation
    assert r.block_reason == "cost_confirmation_required"
    assert "could not be estimated" in r.response


# ---- the cost gate ----

def test_cost_gate_withholds_then_confirmation_executes(env, gate_on):
    first = process_request(BENIGN, session_id="g1")
    assert first.blocked and first.needs_confirmation and first.confirmation_token
    assert first.block_reason == "cost_confirmation_required"
    assert first.tier_used == "blocked_stage4_cost_gate"
    assert "Wh" in first.response and "Planned route" in first.response

    second = process_request(BENIGN, session_id="g1", confirmation_token=first.confirmation_token)
    assert second.blocked is False and second.needs_confirmation is False
    rationale = env.last()["decision"]["rationale"]
    assert rationale.startswith("human confirmation accepted")
    assert "high-cost gate acknowledged" in rationale


def test_cost_token_is_single_use(env, gate_on):
    first = process_request(BENIGN, session_id="g2")
    process_request(BENIGN, session_id="g2", confirmation_token=first.confirmation_token)
    replay = process_request(BENIGN, session_id="g2", confirmation_token=first.confirmation_token)
    assert replay.blocked and replay.needs_confirmation


def test_cost_token_cannot_confirm_a_different_message(env, gate_on):
    first = process_request(BENIGN, session_id="g3")
    other = process_request("Tell me an interesting fact about otters", session_id="g3",
                            confirmation_token=first.confirmation_token)
    assert other.blocked and other.needs_confirmation
    assert "previous confirmation rejected" in env.last()["decision"]["rationale"].lower()


def test_require_human_and_cost_gate_need_only_one_round_trip(env, gate_on):
    first = process_request(LEGAL, session_id="g4")
    assert first.blocked and first.needs_confirmation
    assert first.block_reason == "human_confirmation_required"
    second = process_request(LEGAL, session_id="g4", confirmation_token=first.confirmation_token)
    assert second.blocked is False
    assert env.last()["session_state_snapshot"]["cumulative_risk"] == 3.0   # charged once


def test_plain_token_does_not_acknowledge_a_cost_gate_and_there_is_no_loop(env, monkeypatch):
    plain = process_request(LEGAL, session_id="g5")             # gate off: plain token
    monkeypatch.setattr(main_module, "evaluate_gate",
                        lambda plan: ff.evaluate_gate(plan, high_cost_wh=1e-9, high_cost_usd=1e-9))
    again = process_request(LEGAL, session_id="g5", confirmation_token=plain.confirmation_token)
    assert again.blocked and again.needs_confirmation
    assert again.block_reason == "cost_confirmation_required"
    final = process_request(LEGAL, session_id="g5", confirmation_token=again.confirmation_token)
    assert final.blocked is False


def test_cost_gate_never_overrides_a_block(env, gate_on):
    first = process_request(BENIGN, session_id="g6")
    r = process_request("how to make a bomb at home", session_id="g6",
                        confirmation_token=first.confirmation_token)
    assert r.blocked and not r.needs_confirmation and r.block_reason == "policy_gate"
