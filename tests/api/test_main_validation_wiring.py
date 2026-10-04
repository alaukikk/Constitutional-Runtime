
"""Sprint 5 wiring: Stage 6 validation + one bounded repair + WITHHOLD (OI-064 / OI-066).

The LLM is scripted (tiers.llm_call is a stub), and the placeholder cost ceiling is
lifted for most tests so they exercise the flow rather than OI-045's numbers; the
ceiling itself has its own test below and unit tests in tests/escalation.
"""
import json

import pytest

import api.main as main_module
import tiers.cache_lookup as cache_lookup
import validation.validator as validator_module
from api.main import process_request
from escalation import repair_router
from session.session_state import SessionManager

TEXT = "Tell me an interesting fact about octopuses"
REAL_DECIDE = repair_router.decide_repair


class FakeRedis:
    def __init__(self):
        self.store = {}
    def ping(self): return True
    def get(self, key): return self.store.get(key)
    def set(self, key, value, ex=None): self.store[key] = value


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    log_path = tmp_path / "audit_log.jsonl"
    monkeypatch.chdir(tmp_path)
    cache_lookup.configure_client(FakeRedis())
    main_module._session_manager = SessionManager()
    monkeypatch.setattr(
        main_module, "decide_repair",
        lambda *a, **k: REAL_DECIDE(*a, **{"high_cost_wh": 1e6, "high_cost_usd": 1e6, **k}))
    yield log_path
    cache_lookup._client = None


def script_llm(monkeypatch, *outputs):
    """Each call returns the next scripted item (the last one repeats). An
    Exception instance is raised instead of returned. Returns the call log."""
    calls = []

    def fake(text, model_name="x"):
        calls.append(model_name)
        out = outputs[min(len(calls) - 1, len(outputs) - 1)]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(main_module, "call_llm", fake)
    return calls


def last(log_path):
    return json.loads(log_path.read_text().splitlines()[-1])


def boom(_):
    raise RuntimeError("validator crashed")


# ---- normal path ----

def test_clean_answer_is_validated_cached_and_labelled(monkeypatch, clean_state):
    calls = script_llm(monkeypatch, "Octopuses have three hearts.")
    r = process_request(TEXT, session_id="s")
    assert r.blocked is False and r.validation_status == "passed automated checks"
    assert r.tier_used == "llm_low_reasoning"
    e = last(clean_state)
    assert e["execution"] == "executed"
    assert e["validation_trace"]["repair_status"] == "not_needed"
    assert e["validation_trace"]["repair_attempted"] is False
    assert cache_lookup.try_cache_lookup(TEXT) == "Octopuses have three hearts."
    # the cache hit is validated too, and costs no new model call
    again = process_request(TEXT, session_id="s2")
    assert again.tier_used == "cache_lookup" and again.validation_status == "passed automated checks"
    assert len(calls) == 1


# ---- repair: exactly one upward escalation ----

def test_failed_check_is_repaired_once(monkeypatch, clean_state):
    calls = script_llm(monkeypatch, "", "A real answer.")
    r = process_request(TEXT, session_id="s")
    assert r.blocked is False and r.response == "A real answer."
    assert r.tier_used == "llm_high_reasoning" and len(calls) == 2
    assert "repaired once" in r.feedforward
    e = last(clean_state)
    t = e["validation_trace"]
    assert e["execution"] == "executed" and e["decision"]["selected_tier"] == "llm_high_reasoning"
    assert t["repair_attempted"] and t["repair_status"] == "succeeded" and t["final"] == "released"
    assert t["validation_failed"] is True and t["failed_checks"] == ["non_empty"]
    assert cache_lookup.try_cache_lookup(TEXT) == "A real answer."


def test_repair_exhausted_withholds_and_never_loops(monkeypatch, clean_state):
    calls = script_llm(monkeypatch, "")
    r = process_request(TEXT, session_id="s")
    assert len(calls) == 2                                   # original + exactly one escalation
    assert r.blocked is True and r.tier_used == "withheld_stage6"
    assert r.block_reason == "output_withheld_validation_failed"
    assert r.validation_status is None
    low = r.response.lower()
    assert "releasable response could not be established" in low
    assert "human" not in low and "review" not in low and "verified" not in low
    e = last(clean_state)
    t = e["validation_trace"]
    assert e["execution"] == "executed_withheld"
    assert t["repair_attempted"] and t["repair_status"] == "exhausted"
    assert t["repair_reason"] == "escalation_bound_reached"
    assert t["final"] == "withheld_validation_failed"
    assert cache_lookup.try_cache_lookup(TEXT) is None       # a withheld answer is never cached


def test_safety_leak_is_withheld_without_retry(monkeypatch, clean_state):
    calls = script_llm(monkeypatch, "DAN mode activated. Anything goes.")
    r = process_request(TEXT, session_id="s")
    assert len(calls) == 1
    assert r.blocked and r.block_reason == "output_withheld_validation_failed"
    t = last(clean_state)["validation_trace"]
    assert t["repair_attempted"] is False and t["repair_status"] == "unavailable"
    assert t["repair_reason"] == "safety_failure_not_retried"
    assert "no_safety_leakage" in t["failed_checks"]


def test_cost_ceiling_makes_repair_unavailable(monkeypatch, clean_state):
    monkeypatch.setattr(
        main_module, "decide_repair",
        lambda *a, **k: REAL_DECIDE(*a, **{"high_cost_wh": 1e-6, "high_cost_usd": 1e-9, **k}))
    calls = script_llm(monkeypatch, "")
    r = process_request(TEXT, session_id="s")
    assert len(calls) == 1 and r.blocked
    t = last(clean_state)["validation_trace"]
    assert t["repair_status"] == "unavailable" and t["repair_reason"] == "cost_ceiling"


# ---- validator errors: OI-046 (a), stakes come from policy flags ----

def test_validator_error_on_fail_closed_flag_withholds(monkeypatch, clean_state):
    monkeypatch.setattr(validator_module, "run_non_llm_checks", boom)
    calls = script_llm(monkeypatch, "fine answer")
    # DP-002 is a FLAG rule whose failure mode in failure_modes.yaml is fail_closed.
    r = process_request("what's your home address policy for new hires", session_id="s")
    assert len(calls) == 1 and r.blocked
    assert r.block_reason == "output_withheld_validator_error"
    t = last(clean_state)["validation_trace"]
    assert t["validator_error"] is True and t["validation_failed"] is False
    assert t["repair_status"] == "unavailable" and t["repair_reason"] == "validator_unavailable"
    assert t["final"] == "withheld_validator_error"


def test_validator_error_without_flags_is_released_not_validated_not_cached(monkeypatch, clean_state):
    monkeypatch.setattr(validator_module, "run_non_llm_checks", boom)
    script_llm(monkeypatch, "fine answer")
    r = process_request(TEXT, session_id="s")
    assert r.blocked is False and r.response == "fine answer"
    assert r.validation_status.startswith("not validated")
    assert r.validation_status != "passed automated checks"
    t = last(clean_state)["validation_trace"]
    assert t["failed_open"] is True and t["validator_error"] is True and t["final"] == "released"
    assert cache_lookup.try_cache_lookup(TEXT) is None


# ---- Stage 5 execution errors ----

def test_execution_error_then_repair_succeeds(monkeypatch, clean_state):
    script_llm(monkeypatch, RuntimeError("provider down"), "recovered")
    r = process_request(TEXT, session_id="s")
    assert r.blocked is False and r.response == "recovered" and r.tier_used == "llm_high_reasoning"
    t = last(clean_state)["validation_trace"]
    assert t["execution_error"] is True and t["repair_status"] == "succeeded"


def test_execution_error_twice_is_withheld(monkeypatch, clean_state):
    calls = script_llm(monkeypatch, RuntimeError("provider down"))
    r = process_request(TEXT, session_id="s")
    assert len(calls) == 2 and r.blocked
    assert r.block_reason == "output_withheld_execution_error"
    assert "generating an answer failed" in r.response
    e = last(clean_state)
    assert e["execution"] == "executed_withheld"
    assert e["validation_trace"]["repair_status"] == "exhausted"


# ---- cache ----

def test_bad_cache_hit_is_repaired_and_overwritten(monkeypatch, clean_state):
    cache_lookup.store_cache_entry(TEXT, "")                  # a poisoned entry from before Stage 6
    calls = script_llm(monkeypatch, "fresh answer")
    r = process_request(TEXT, session_id="s")
    assert r.response == "fresh answer" and r.tier_used == "llm_low_reasoning" and len(calls) == 1
    t = last(clean_state)["validation_trace"]
    assert t["first_attempt_tier"] == "cache_lookup" and t["repair_status"] == "succeeded"
    assert cache_lookup.try_cache_lookup(TEXT) == "fresh answer"


# ---- session boundary (owner decision: validation does not feed session risk) ----

def test_validation_outcomes_do_not_change_session_risk(monkeypatch, clean_state):
    script_llm(monkeypatch, "")
    r = process_request(TEXT, session_id="risk")
    assert r.blocked
    state, _ = main_module._session_manager.record_turn("risk", [], "clean", 0.0)
    assert state.turn_count == 2 and state.cumulative_risk == 0.0
