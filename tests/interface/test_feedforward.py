
import math

import pytest

import interface.feedforward as ff
from policy.schemas import MethodTier as T, RequestClassification, RequestType as R
from triage.decision import plan_request


def fixed(category, confidence=0.9):
    return lambda text: RequestClassification(category, confidence, text)


LOOKUP_PLAN = plan_request("what is the capital of Japan")
GEN_PLAN = plan_request("write a short story about a dragon")


def test_every_tier_has_a_label():
    for tier in T:
        assert tier in ff._LABELS


def test_worst_case_sums_exactly_the_attempted_rungs():
    c = ff.worst_case(LOOKUP_PLAN)
    attempted = [s for s in LOOKUP_PLAN.steps if s.attempt]
    skipped = [s for s in LOOKUP_PLAN.steps if not s.attempt]
    assert not skipped or all(s not in attempted for s in skipped)
    assert c.wh == pytest.approx(sum(s.estimate.tier_estimate.est_energy_wh for s in attempted))
    assert c.wh_high == pytest.approx(sum(s.estimate.wh_high for s in attempted))
    assert c.usd == pytest.approx(sum(s.estimate.tier_estimate.est_dollar_cost for s in attempted))
    assert c.wh_high >= c.wh


def test_ordinary_requests_are_not_gated_by_default():
    for plan in (LOOKUP_PLAN, GEN_PLAN):
        gate = ff.evaluate_gate(plan)
        assert gate.required is False and gate.reasons == ()


def test_tiny_energy_limit_gates_and_says_why():
    gate = ff.evaluate_gate(GEN_PLAN, high_cost_wh=1e-9)
    assert gate.required and any("Wh" in r for r in gate.reasons)


def test_tiny_dollar_limit_gates_and_says_why():
    gate = ff.evaluate_gate(GEN_PLAN, high_cost_usd=1e-12)
    assert gate.required and any("$" in r for r in gate.reasons)


def test_gate_uses_the_upper_bound_not_the_central_estimate():
    c = ff.worst_case(GEN_PLAN)
    between = (c.wh + c.wh_high) / 2          # above central, at or below the bound
    assert ff.evaluate_gate(GEN_PLAN, high_cost_wh=between).required is True


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf])
def test_bad_limits_are_loud(bad):
    with pytest.raises(ValueError):
        ff.evaluate_gate(GEN_PLAN, high_cost_wh=bad)
    with pytest.raises(ValueError):
        ff.evaluate_gate(GEN_PLAN, high_cost_usd=bad)


@pytest.mark.parametrize("bad", [True, "3"])
def test_badly_typed_limits_are_loud(bad):
    with pytest.raises(TypeError):
        ff.evaluate_gate(GEN_PLAN, high_cost_wh=bad)


def test_gate_evaluation_error_fails_closed(monkeypatch):
    def boom(plan):
        raise RuntimeError("estimator exploded")

    monkeypatch.setattr(ff, "worst_case", boom)
    gate = ff.evaluate_gate(GEN_PLAN)
    assert gate.required is True
    assert "could not be estimated" in gate.reasons[0]


# ---- text ----

def test_preview_lists_the_route_in_order_with_the_model_and_worst_case():
    text = ff.preview_text(LOOKUP_PLAN)
    assert text.index("saved answer") < text.index("rule-based solver") < text.index("language model")
    llm_model = LOOKUP_PLAN.step_for(T.LLM_LOW_REASONING).model_name
    assert llm_model in text
    assert "Worst-case" in text and "not measurements" in text


def test_text_never_exposes_classifier_internals():
    for plan in (LOOKUP_PLAN, GEN_PLAN, plan_request("I need legal advice about my lease")):
        for text in (ff.preview_text(plan), ff.outcome_text(plan, T.LLM_LOW_REASONING)):
            low = text.lower()
            for forbidden in ("confidence", "floor", "keyword", "eligible",
                              plan.classification.category.value):
                assert forbidden not in low


def test_outcome_names_the_answering_step():
    text = ff.outcome_text(GEN_PLAN, T.DETERMINISTIC)
    assert text.startswith("Answered by: rule-based solver")


def test_outcome_rejects_a_tier_that_was_not_attempted():
    with pytest.raises(ValueError):
        ff.outcome_text(GEN_PLAN, T.RAG_SMALL_MODEL)


def test_render_failures_fail_open(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("template bug")

    monkeypatch.setattr(ff, "preview_text", boom)
    monkeypatch.setattr(ff, "outcome_text", boom)
    assert ff.safe_preview(GEN_PLAN) is None
    assert ff.safe_outcome(GEN_PLAN, T.LLM_LOW_REASONING) is None


def test_safe_helpers_pass_text_through_when_healthy():
    assert ff.safe_preview(GEN_PLAN) == ff.preview_text(GEN_PLAN)
    assert ff.safe_outcome(GEN_PLAN, T.LLM_LOW_REASONING) == ff.outcome_text(GEN_PLAN, T.LLM_LOW_REASONING)
