
"""
Stage 1 — Constitutional Policy Gate.
Runs on every path, including the deterministic/non-AI branch.

Fail-open vs fail-closed principle (see docs/CONSTITUTION.md discussion):
severity of the *action* determines the failure behavior, not how sensitive
the rule's topic sounds. block/require_human rules fail closed (escalate to
BLOCK on error). flag rules fail open (a flag is an annotation, not a gate,
so a missed flag is a much smaller cost than a false BLOCK from a code bug).

Fail-open does NOT mean silent: an error on a fail-open rule still gets
logged as a warning, so an engineering bug quietly suppressing flags for
weeks doesn't go unnoticed just because the user-facing behavior looks
identical to "no match found."
"""
from __future__ import annotations
import logging
from pathlib import Path
import yaml

from policy.schemas import PolicyFlag, PolicyAction, RiskCategory

logger = logging.getLogger("policy.engine")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # policy/engine.py -> policy/ -> project root
_CONSTITUTION_PATH = _PROJECT_ROOT / "config" / "constitution.yaml"
_FAILURE_MODES_PATH = _PROJECT_ROOT / "config" / "failure_modes.yaml"

_ACTION_SEVERITY = {
    PolicyAction.ALLOW: 0,
    PolicyAction.FLAG: 1,
    PolicyAction.REQUIRE_HUMAN: 2,
    PolicyAction.BLOCK: 3,
}


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


class PolicyEngine:
    def __init__(self, constitution_path: Path = _CONSTITUTION_PATH, failure_modes_path: Path = _FAILURE_MODES_PATH):
        self._constitution = _load_yaml(constitution_path)
        self._failure_modes = _load_yaml(failure_modes_path)
        self._rules = self._constitution.get("rules", [])
        self._default_fail_closed = self._failure_modes.get("default", {}).get("fail_closed", True)
        self._rule_failure_modes = self._failure_modes.get("rules", {})

    def _fail_closed_for(self, rule_id: str) -> bool:
        return self._rule_failure_modes.get(rule_id, {}).get("fail_closed", self._default_fail_closed)

    def evaluate(self, normalized_text: str) -> tuple[list[PolicyFlag], PolicyAction]:
        flags: list[PolicyFlag] = []
        lowered = (normalized_text or "").lower()

        for rule in self._rules:
            rule_id = rule.get("rule_id", "UNKNOWN")
            try:
                keywords = rule.get("keywords", [])
                if any(kw.lower() in lowered for kw in keywords):
                    flags.append(PolicyFlag(
                        rule_id=rule_id,
                        risk_category=RiskCategory(rule["risk_category"]),
                        action=PolicyAction(rule["action"]),
                        reason=rule.get("description", "keyword match"),
                    ))
            except Exception as e:
                if self._fail_closed_for(rule_id):
                    logger.warning(
                        "policy rule '%s' errored during evaluation (%s); fail-closed, escalating to BLOCK",
                        rule_id, e,
                    )
                    # The error is usually in keyword matching, not the category
                    # field, so preserve the rule's real risk_category where we
                    # can -- an audit record with the wrong category is its own
                    # small accuracy bug. Only fall back if the category itself
                    # is what's unparseable.
                    try:
                        escalated_category = RiskCategory(rule["risk_category"])
                    except Exception:
                        escalated_category = RiskCategory.DANGEROUS_CONTENT
                        logger.warning(
                            "policy rule '%s' also has an unparseable risk_category; "
                            "audit record will use fallback category '%s'",
                            rule_id, escalated_category.value,
                        )
                    flags.append(PolicyFlag(
                        rule_id=rule_id,
                        risk_category=escalated_category,
                        action=PolicyAction.BLOCK,
                        reason=f"rule '{rule_id}' errored during evaluation ({e}); failed closed",
                    ))
                else:
                    # Fail-open: request proceeds without this rule's flag, but
                    # we still surface the error so it isn't a silent blind spot.
                    logger.warning(
                        "policy rule '%s' errored during evaluation (%s); fail-open, "
                        "request proceeds WITHOUT this rule's flag this turn",
                        rule_id, e,
                    )

        most_severe = PolicyAction.ALLOW
        for flag in flags:
            if _ACTION_SEVERITY[flag.action] > _ACTION_SEVERITY[most_severe]:
                most_severe = flag.action

        return flags, most_severe


_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine
