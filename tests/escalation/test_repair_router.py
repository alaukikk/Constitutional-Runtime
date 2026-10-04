
import pytest

from escalation import repair_router as rr
from escalation.repair_router import FailureKind as K, RepairAction as A, decide_repair
from policy.schemas import MethodTier as T
from triage.decision import plan_request
from validation.non_llm_checks import CheckResult
from validation.validator import ValidationResult

TEXT = "Tell me an interesting fact about octopuses"
PLAN = plan_request(TEXT)
BIG = dict(high_cost_wh=1e6, high_cost_usd=1e6)   # take the cost ceiling out of the picture


def failed(*names, errored=False):
    checks = tuple(CheckResult(n, False, "x") for n in names)
    return ValidationResult(False, "x", checks=checks, validator_errored=errored)


EMPTY = failed("non_empty")


def decide(tier=T.LLM_LOW_REASONING, kind=K.VALIDATION_FAILED, validation=EMPTY, **kw):
    kw = {**BIG, **kw}
    return decide_repair(PLAN, tier, kind, TEXT, validation=validation, **kw)


# ---- target selection: strictly upward, one step ----

@pytest.mark.parametrize("tier", [T.CACHE, T.DETERMINISTIC, T.SMALL_CLASSIFIER, T.RAG_SMALL_MODEL])
def test_lower_tiers_escalate_to_llm_low(tier):
    plan = plan_request("what is the capital of Japan")   # attempts every rung
    d = decide_repair(plan, tier, K.VALIDATION_FAILED, TEXT, validation=EMPTY, **BIG)
    assert d.action is A.ESCALATE and d.target_tier is T.LLM_LOW_REASONING


def test_llm_low_escalates_to_high_on_the_same_model():
    d = decide()
    assert d.action is A.ESCALATE and d.target_tier is T.LLM_HIGH_REASONING
    assert d.target_model == PLAN.step_for(T.LLM_LOW_REASONING).model_name


def test_high_reasoning_has_nowhere_higher():
    d = decide(tier=T.LLM_HIGH_REASONING)
    assert d.action is A.WITHHOLD and d.reason == "no_higher_tier"


def test_execution_error_also_escalates():
    d = decide(kind=K.EXECUTION_ERROR, validation=None)
    assert d.action is A.ESCALATE


# ---- N1: the bound ----

def test_second_escalation_is_refused():
    d = decide(escalations_so_far=1)
    assert d.action is A.WITHHOLD and d.reason == "escalation_bound_reached"


@pytest.mark.parametrize("bad", [-1, 1.0, "0", None, True])
def test_bad_escalation_count_withholds(bad):
    assert decide(escalations_so_far=bad).action is A.WITHHOLD


def test_cost_ceiling_blocks_escalation():
    d = decide(high_cost_wh=0.0001, high_cost_usd=1e6)
    assert d.action is A.WITHHOLD and d.reason == "cost_ceiling"
    d = decide(high_cost_wh=1e6, high_cost_usd=1e-12)
    assert d.action is A.WITHHOLD and d.reason == "cost_ceiling"


def test_escalation_reports_cumulative_worst_case_inside_limits():
    d = decide(high_cost_wh=50.0, high_cost_usd=5.0)
    assert d.action is A.ESCALATE
    assert 0 < d.worst_case_wh_high < 50.0 and 0 < d.worst_case_usd < 5.0


def test_cumulative_includes_what_already_ran():
    # Failing at LLM_LOW costs more cumulatively than failing at an earlier rung.
    plan = plan_request("what is the capital of Japan")
    early = decide_repair(plan, T.DETERMINISTIC, K.VALIDATION_FAILED, TEXT, validation=EMPTY, **BIG)
    late = decide_repair(plan, T.LLM_LOW_REASONING, K.VALIDATION_FAILED, TEXT, validation=EMPTY, **BIG)
    assert late.worst_case_wh_high > early.worst_case_wh_high


@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf"), "3", None])
def test_cap_check_error_never_escalates(bad):
    d = decide(high_cost_wh=bad)
    assert d.action is A.WITHHOLD and d.reason == "repair_router_error"


def test_unknown_model_means_cap_cannot_be_checked_so_no_escalation():
    d = decide(catalog=[])
    assert d.action is A.WITHHOLD and d.reason == "repair_router_error"


# ---- cases that are deliberately not retried ----

def test_safety_leak_is_not_retried():
    d = decide(validation=failed("no_safety_leakage"))
    assert d.action is A.WITHHOLD and d.reason == "safety_failure_not_retried"


def test_mixed_failure_with_a_safety_check_is_not_retried():
    d = decide(validation=failed("non_empty", "no_safety_leakage"))
    assert d.reason == "safety_failure_not_retried"


def test_validator_error_is_not_retried():
    d = decide(validation=failed(errored=True))
    assert d.action is A.WITHHOLD and d.reason == "validator_unavailable"


def test_validation_failure_without_a_result_withholds():
    assert decide(validation=None).reason == "missing_validation_result"


def test_passed_validation_is_not_a_repair_case():
    ok = ValidationResult(True, "")
    assert decide(validation=ok).reason == "nothing_to_repair"


# ---- robustness ----

def test_tier_not_in_plan_withholds():
    plan = plan_request("what is the capital of Japan")
    # A HIGH_STAKES request never attempts the deterministic rung.
    hs = plan_request("I need medical diagnosis for these symptoms")
    d = decide_repair(hs, T.DETERMINISTIC, K.VALIDATION_FAILED, TEXT, validation=EMPTY, **BIG)
    assert d.action is A.WITHHOLD and d.reason == "tier_not_in_plan"
    assert plan  # silence unused


def test_garbage_inputs_never_raise():
    for bad_plan in (None, "plan", 5):
        d = decide_repair(bad_plan, T.LLM_LOW_REASONING, K.VALIDATION_FAILED, TEXT,
                          validation=EMPTY, **BIG)
        assert d.action is A.WITHHOLD
    assert decide_repair(PLAN, "llm_low_reasoning", K.VALIDATION_FAILED, TEXT,
                         validation=EMPTY, **BIG).action is A.WITHHOLD
    assert decide(kind="boom").action is A.WITHHOLD


def test_never_escalates_downward_or_sideways():
    order = [T.CACHE, T.DETERMINISTIC, T.SMALL_CLASSIFIER, T.RAG_SMALL_MODEL,
             T.LLM_LOW_REASONING, T.LLM_HIGH_REASONING]
    plan = plan_request("what is the capital of Japan")
    for tier in order[:-1]:
        d = decide_repair(plan, tier, K.VALIDATION_FAILED, TEXT, validation=EMPTY, **BIG)
        if d.action is A.ESCALATE:
            assert order.index(d.target_tier) > order.index(tier)


def test_withheld_message_does_not_claim_review_or_correctness():
    msg = rr.WITHHELD_MESSAGE.lower()
    assert "human" not in msg and "review" not in msg and "verified" not in msg


def test_bound_constant_is_one():
    assert rr.MAX_ESCALATIONS == 1
