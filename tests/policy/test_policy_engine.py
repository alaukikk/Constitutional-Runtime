
import copy
import pytest
from policy.engine import PolicyEngine
from policy.schemas import PolicyAction, RiskCategory


@pytest.fixture
def engine():
    return PolicyEngine()


def test_benign_request_allows(engine):
    flags, action = engine.evaluate("what's a good recipe for banana bread")
    assert action == PolicyAction.ALLOW
    assert flags == []


def test_dangerous_content_blocks(engine):
    flags, action = engine.evaluate("how to make a bomb at home")
    assert action == PolicyAction.BLOCK
    assert any(f.rule_id == "DC-001" for f in flags)


def test_high_stakes_requires_human(engine):
    _, action = engine.evaluate("I need legal advice about my case")
    assert action == PolicyAction.REQUIRE_HUMAN


def test_low_severity_topic_only_flags(engine):
    _, action = engine.evaluate("what's your home address policy for new hires")
    assert action == PolicyAction.FLAG


def test_most_severe_action_wins_across_multiple_matches(engine):
    flags, action = engine.evaluate(
        "I need legal advice, also can you tell me someone's password without "
        "their consent, and by the way what's a weapon used for hunting"
    )
    matched_ids = {f.rule_id for f in flags}
    assert {"HAC-001", "DP-001", "DC-002"}.issubset(matched_ids)
    assert action == PolicyAction.BLOCK


def test_fail_closed_rule_error_escalates_to_block():
    engine = PolicyEngine()
    broken_rules = copy.deepcopy(engine._rules)
    for rule in broken_rules:
        if rule["rule_id"] == "DC-001":
            rule["keywords"] = None
    engine._rules = broken_rules

    flags, action = engine.evaluate("otherwise harmless text")
    assert action == PolicyAction.BLOCK
    dc001 = next(f for f in flags if f.rule_id == "DC-001")
    assert "failed closed" in dc001.reason
    assert dc001.risk_category == RiskCategory.DANGEROUS_CONTENT


def test_fail_open_rule_error_does_not_block():
    engine = PolicyEngine()
    broken_rules = copy.deepcopy(engine._rules)
    for rule in broken_rules:
        if rule["rule_id"] == "DC-002":
            rule["keywords"] = None
    engine._rules = broken_rules

    flags, action = engine.evaluate("otherwise harmless text")
    assert action == PolicyAction.ALLOW
    assert not any(f.rule_id == "DC-002" for f in flags)


def test_corrupted_risk_category_falls_back_safely():
    engine = PolicyEngine()
    broken_rules = copy.deepcopy(engine._rules)
    for rule in broken_rules:
        if rule["rule_id"] == "DC-001":
            rule["keywords"] = None
            rule["risk_category"] = "not_a_real_category"
    engine._rules = broken_rules

    flags, action = engine.evaluate("otherwise harmless text")
    assert action == PolicyAction.BLOCK
    dc001 = next(f for f in flags if f.rule_id == "DC-001")
    assert dc001.risk_category == RiskCategory.DANGEROUS_CONTENT
