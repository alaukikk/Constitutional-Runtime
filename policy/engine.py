

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

Matching views (CP-002, Part A). evaluate() may also receive the matching views Stage 0 built from
the raw request (guardrails/match_view.py). A keyword matches when it is found in the v1 normalized
text (exactly as before) OR in a view, against keywords canonicalised the same way (apostrophes
dropped, hyphens and separators turned into one space, look-alike letters folded). Views can only ADD
matches. The v1 check runs first and its result is kept: the view step runs only for a rule v1 did not
match, and if it raises, that rule's failure_modes.yaml behaviour applies as for any other error
(fail-closed rules escalate to BLOCK, fail-open rules log a warning and keep the v1 result). With no
views, behaviour is identical to before. config/constitution.yaml is not edited.
"""
from __future__ import annotations
import logging
from pathlib import Path
import yaml

from guardrails.match_view import MatchViews, canon_keyword
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
        # Keywords in matching-view form, computed once here and memoised by content, so a request
        # costs no canonicalisation. A malformed rule is skipped here; evaluate() reports it as before.
        self._canon_memo: dict[tuple[str, ...], tuple[str, ...]] = {}
        for rule in self._rules:
            try:
                self._canonical(tuple(rule.get("keywords") or ()))
            except Exception:
                pass

    def _canonical(self, keywords: tuple[str, ...]) -> tuple[str, ...]:
        cached = self._canon_memo.get(keywords)
        if cached is None:
            # An empty canonical keyword (only apostrophes/separators) would match everything: skip it.
            cached = tuple(c for c in (canon_keyword(k) for k in keywords) if c)
            self._canon_memo[keywords] = cached
        return cached

    def _view_match(self, rule: dict, view_texts: tuple[str, ...]) -> bool:
        """True when a canonical keyword of this rule occurs in any matching view."""
        canonical = self._canonical(tuple(rule.get("keywords", [])))
        return any(kw in text for text in view_texts for kw in canonical)

    def _fail_closed_for(self, rule_id: str) -> bool:
        return self._rule_failure_modes.get(rule_id, {}).get("fail_closed", self._default_fail_closed)

    def evaluate(self, normalized_text: str,
                 match_views: MatchViews | None = None) -> tuple[list[PolicyFlag], PolicyAction]:
        # A wrong type is a wiring bug, not data: raise rather than silently matching v1 only.
        if match_views is not None and not isinstance(match_views, MatchViews):
            raise TypeError(f"match_views must be a MatchViews or None, not {type(match_views).__name__}")
        flags: list[PolicyFlag] = []
        lowered = (normalized_text or "").lower()
        view_texts = match_views.flat if match_views is not None else ()

        for rule in self._rules:
            rule_id = rule.get("rule_id", "UNKNOWN")
            try:
                keywords = rule.get("keywords", [])
                matched = any(kw.lower() in lowered for kw in keywords)    # v1 result, kept as is
                if not matched and view_texts:
                    matched = self._view_match(rule, view_texts)          # views only ADD matches
                if matched:
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
