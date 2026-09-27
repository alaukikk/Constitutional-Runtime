
import yaml
import pytest
from policy.schemas import RiskCategory, PolicyAction


@pytest.fixture
def constitution():
    with open("config/constitution.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def failure_modes():
    with open("config/failure_modes.yaml") as f:
        return yaml.safe_load(f)


def test_constitution_has_rules(constitution):
    assert len(constitution.get("rules", [])) > 0


def test_rule_ids_are_unique(constitution):
    ids = [r["rule_id"] for r in constitution["rules"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("field", ["rule_id", "risk_category", "action", "description", "keywords"])
def test_every_rule_has_required_fields(constitution, field):
    for rule in constitution["rules"]:
        assert field in rule, f"{rule.get('rule_id', '<unknown>')} missing '{field}'"


def test_every_rule_risk_category_is_valid_enum(constitution):
    for rule in constitution["rules"]:
        RiskCategory(rule["risk_category"])


def test_every_rule_action_is_valid_enum(constitution):
    for rule in constitution["rules"]:
        PolicyAction(rule["action"])


def test_every_rule_has_at_least_one_keyword(constitution):
    for rule in constitution["rules"]:
        assert len(rule["keywords"]) > 0


def test_failure_modes_has_default_fallback(failure_modes):
    assert "default" in failure_modes and "fail_closed" in failure_modes["default"]


def test_failure_modes_entries_reference_real_rule_ids(constitution, failure_modes):
    real_ids = {r["rule_id"] for r in constitution["rules"]}
    for rule_id in failure_modes.get("rules", {}):
        assert rule_id in real_ids, f"failure_modes.yaml references unknown rule_id '{rule_id}'"
