import pytest

from cost.model_registry import MODEL_CATALOG
from policy.schemas import (
    MethodTier as T, PolicyAction, PolicyFlag, RequestClassification,
    RequestType as R, RiskCategory,
)
from triage.decision import DEFAULT_MIN_CONFIDENCE, plan_request

LARGE = max(MODEL_CATALOG, key=lambda m: m.capability_score)
BY_NAME = {m.name: m for m in MODEL_CATALOG}

FULL = (T.CACHE, T.DETERMINISTIC, T.SMALL_CLASSIFIER, T.RAG_SMALL_MODEL, T.LLM_LOW_REASONING)
NO_AI_MIDDLE = (T.CACHE, T.DETERMINISTIC, T.LLM_LOW_REASONING)
HIGH = (T.CACHE, T.LLM_LOW_REASONING)


def fixed(category, confidence):
    return lambda text: RequestClassification(category, confidence, text)


# (text, expected attempt order). Includes deliberate "should NOT escalate"
# cases (cheap tiers stay on the ladder) and "must escalate" cases.
GOLDEN = [
    ("what is the capital of Japan", FULL),
    ("define photosynthesis", FULL),
    ("calculate 45 * 3", FULL),
    ("2 + 2", NO_AI_MIDDLE),                      # UNKNOWN to the classifier, but the
                                                  # self-gating deterministic rung must still run
    ("write a short story about a dragon", NO_AI_MIDDLE),
    ("should I take this job offer", NO_AI_MIDDLE),
    ("classify this email as spam or not", NO_AI_MIDDLE),
    ("Tell me an interesting fact about octopuses", NO_AI_MIDDLE),
    ("hmm interesting", NO_AI_MIDDLE),
    ("I need legal advice about my divorce", HIGH),
    ("what is the best medical diagnosis for chest pain", HIGH),   # keyword-dilution case
]


@pytest.mark.parametrize("text,expected", GOLDEN)
def test_golden_attempt_order(text, expected):
    assert plan_request(text).attempt_order == expected


def test_high_stakes_uses_a_capability_floor_model():
    plan = plan_request("I need legal advice about my divorce")
    model = BY_NAME[plan.step_for(T.LLM_LOW_REASONING).model_name]
    assert model.capability_score >= 0.7


@pytest.mark.parametrize("category", list(R))
def test_cache_first_llm_last_and_always_attempted(category):
    plan = plan_request("anything", classifier=fixed(category, 0.9))
    assert plan.attempt_order[0] == T.CACHE
    assert plan.attempt_order[-1] == T.LLM_LOW_REASONING


def test_unknown_never_gets_small_or_rag_even_at_high_confidence():
    plan = plan_request("x", classifier=fixed(R.UNKNOWN, 0.99))
    assert T.SMALL_CLASSIFIER not in plan.attempt_order
    assert T.RAG_SMALL_MODEL not in plan.attempt_order


# ---- confidence floor: escalate-only ----

def test_low_confidence_in_eligible_category_escalates():
    plan = plan_request("x", classifier=fixed(R.LOOKUP, 0.3))
    assert plan.attempt_order == NO_AI_MIDDLE
    assert "below the floor" in plan.step_for(T.RAG_SMALL_MODEL).reason


def test_lowering_the_floor_admits_the_same_request():
    plan = plan_request("x", classifier=fixed(R.LOOKUP, 0.3), min_confidence=0.2)
    assert plan.attempt_order == FULL


def test_confidence_never_admits_an_ineligible_category():
    for conf in (0.0, 0.5, 0.75, 1.0):
        plan = plan_request("x", classifier=fixed(R.GENERATION, conf), min_confidence=0.0)
        assert T.SMALL_CLASSIFIER not in plan.attempt_order


def test_raising_confidence_only_ever_adds_cheap_tiers():
    prev = set()
    for conf in (0.0, 0.2, 0.39, 0.4, 0.6, 0.9):
        cur = set(plan_request("x", classifier=fixed(R.LOOKUP, conf)).attempt_order)
        assert prev <= cur
        prev = cur


def test_default_floor_matches_classifier_default():
    assert DEFAULT_MIN_CONFIDENCE == 0.4


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_bad_min_confidence_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        plan_request("x", min_confidence=bad)


# ---- classifier failure: fail conservative ----

def _boom(text):
    raise RuntimeError("classifier down")


@pytest.mark.parametrize("clf", [_boom, lambda t: "lookup", lambda t: None])
def test_classifier_failure_routes_conservatively(clf):
    plan = plan_request("what is the capital of Japan", classifier=clf)
    assert plan.classifier_failed
    assert plan.classification.category == R.UNKNOWN
    assert plan.attempt_order == NO_AI_MIDDLE
    assert plan.step_for(T.LLM_LOW_REASONING).model_name == LARGE.name
    assert "classifier failed" in plan.rationale


# ---- audit output ----

def test_every_step_has_a_reason_and_estimate():
    plan = plan_request("what is the capital of Japan")
    assert [s.tier for s in plan.steps] == list(FULL)
    for s in plan.steps:
        assert s.reason
        assert s.estimate is not None
    assert plan.step_for(T.CACHE).model_name is None
    assert plan.step_for(T.LLM_LOW_REASONING).model_name is not None


def test_skip_reasons_are_in_the_rationale():
    plan = plan_request("write a short story about a dragon")
    assert "not cheap-tier eligible" in plan.rationale


def test_decision_for_carries_tier_model_cost_and_flags():
    flag = PolicyFlag("DC-002", RiskCategory.DANGEROUS_CONTENT, PolicyAction.FLAG, "t")
    plan = plan_request("write a short story about a dragon")
    dec = plan.decision_for(T.LLM_LOW_REASONING, [flag])
    llm = plan.step_for(T.LLM_LOW_REASONING)
    assert dec.selected_tier == T.LLM_LOW_REASONING
    assert dec.selected_model == llm.model_name
    assert dec.cost_estimate == llm.estimate.tier_estimate
    assert dec.policy_flags == [flag]
    assert "answered" in dec.rationale


def test_decision_for_rejects_a_tier_that_was_not_attempted():
    plan = plan_request("write a short story about a dragon")
    with pytest.raises(ValueError):
        plan.decision_for(T.RAG_SMALL_MODEL)


def test_plan_is_deterministic():
    a = plan_request("what is the capital of Japan")
    b = plan_request("what is the capital of Japan")
    assert a.attempt_order == b.attempt_order
    assert a.rationale == b.rationale
