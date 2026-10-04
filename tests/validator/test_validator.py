
import pytest

import validation.validator as validator
from policy.schemas import MethodTier, PolicyAction, PolicyFlag, RiskCategory
from validation.non_llm_checks import MAX_OUTPUT_CHARS, run_non_llm_checks
from validation.validator import validate_output

T = MethodTier.LLM_LOW_REASONING


def flag(rule_id="DC-002", action=PolicyAction.FLAG):
    return PolicyFlag(rule_id, RiskCategory.DANGEROUS_CONTENT, action, "test")


def boom(_):
    raise RuntimeError("check crashed")


# ---- individual checks ----

def test_clean_output_passes_every_check():
    assert all(r.passed for r in run_non_llm_checks("The capital of France is Paris."))


@pytest.mark.parametrize("text,check", [
    (None, "non_empty"),
    ("", "non_empty"),
    ("   \n ", "non_empty"),
    # Explicit id: pytest otherwise embeds the 50k-char string in the test id, and
    # on Windows that id is copied into the PYTEST_CURRENT_TEST env var, which
    # is capped at 32,767 characters.
    pytest.param("a" * (MAX_OUTPUT_CHARS + 1), "within_length", id="oversized_output"),
    ("hello\x00world", "no_control_chars"),
    ("DAN mode activated. No limits.", "no_safety_leakage"),
    ("key: sk-abcdefghijklmnopqrstuvwx1234", "no_safety_leakage"),
])
def test_bad_outputs_fail_the_expected_check(text, check):
    failed = {r.name for r in run_non_llm_checks(text) if not r.passed}
    assert check in failed


def test_tabs_and_newlines_are_allowed():
    assert all(r.passed for r in run_non_llm_checks("line1\n\tline2\r\n"))


def test_all_checks_run_so_every_failure_is_reported():
    failed = {r.name for r in run_non_llm_checks("\x00" * 3 + " DAN mode activated")}
    assert {"no_control_chars", "no_safety_leakage"} <= failed


def test_crashing_check_becomes_a_failed_check(monkeypatch):
    import validation.non_llm_checks as n
    monkeypatch.setattr(n, "_CHECKS", (("explodes", boom),))
    (r,) = n.run_non_llm_checks("x")
    assert (r.passed, r.reason) == (False, "check_internal_error")


# ---- validator: normal pass / fail ----

def test_clean_output_passes_with_no_confidence_claim():
    r = validate_output("q", "Paris", T, [])
    assert r.passed and r.reason == "" and r.check_type == "non_llm"
    assert r.confidence is None and not r.validator_errored


def test_failed_check_is_a_failure_not_a_fail_open_even_for_low_stakes():
    r = validate_output("q", "", T, [], fail_closed_for=lambda _: False)
    assert not r.passed and not r.failed_open and "non_empty" in r.reason


# ---- validator error: OI-046 (a), stakes come from policy flags only ----

def _force_error(monkeypatch):
    monkeypatch.setattr(validator, "run_non_llm_checks", boom)


def test_error_with_fail_closed_flag_withholds(monkeypatch):
    _force_error(monkeypatch)
    r = validate_output("q", "ok", T, [flag("DP-001", PolicyAction.BLOCK)],
                        fail_closed_for=lambda rid: rid == "DP-001")
    assert not r.passed and r.validator_errored and not r.failed_open
    assert r.reason == "validator_error_failed_closed"


def test_error_with_only_fail_open_flags_releases_and_marks_it(monkeypatch, caplog):
    _force_error(monkeypatch)
    with caplog.at_level("WARNING", logger="validation.validator"):
        r = validate_output("q", "ok", T, [flag("DC-002")], fail_closed_for=lambda _: False)
    assert r.passed and r.failed_open and r.validator_errored
    assert "FAILING OPEN" in caplog.text


def test_error_with_no_flags_is_low_stakes(monkeypatch):
    _force_error(monkeypatch)
    r = validate_output("q", "ok", T, [], fail_closed_for=lambda _: True)
    assert r.passed and r.failed_open   # no flags -> nothing marks it high-stakes


def test_one_fail_closed_flag_among_fail_open_ones_wins(monkeypatch):
    _force_error(monkeypatch)
    r = validate_output("q", "ok", T, [flag("DC-002"), flag("HAC-001", PolicyAction.REQUIRE_HUMAN)],
                        fail_closed_for=lambda rid: rid == "HAC-001")
    assert not r.passed and not r.failed_open


def test_unresolvable_stakes_fails_closed(monkeypatch):
    _force_error(monkeypatch)
    def bad_resolver(_):
        raise RuntimeError("yaml unreadable")
    r = validate_output("q", "ok", T, [flag()], fail_closed_for=bad_resolver)
    assert not r.passed and r.reason == "validator_error_failed_closed"


def test_classifier_high_stakes_is_not_an_input():
    # Structural guard for OI-046 (a): the signature carries no classifier category.
    import inspect
    assert "classification" not in inspect.signature(validate_output).parameters
    assert "request_type" not in inspect.signature(validate_output).parameters


def test_default_resolver_uses_real_failure_modes_yaml(monkeypatch):
    _force_error(monkeypatch)
    # DP-001 is fail_closed in config/failure_modes.yaml; DC-002 is fail-open.
    closed = validate_output("q", "ok", T, [flag("DP-001", PolicyAction.BLOCK)])
    opened = validate_output("q", "ok", T, [flag("DC-002")])
    assert not closed.passed
    assert opened.passed and opened.failed_open
