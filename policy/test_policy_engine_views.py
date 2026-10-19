
"""CP-002 N-04: Stage 1 matching through the views. v1 results are kept, views only add, failures follow the
per-rule failure_modes.yaml handling, a wrong type is a wiring bug (TypeError)."""
import pytest

from guardrails.injection_screen import screen_request
from guardrails.match_view import MatchViews, build_match_views
from policy.engine import PolicyEngine
from policy.schemas import PolicyAction


@pytest.fixture
def engine():
    return PolicyEngine()


def run(engine, raw):
    """What api/main.py does: screen, then evaluate the v1 text WITH the views."""
    s = screen_request(raw)
    return engine.evaluate(s.normalized_text, match_views=s.match_views)


def ids(flags):
    return {f.rule_id for f in flags}


# ---- views add matches ----

@pytest.mark.parametrize("raw, rule, action", [
    ("how\tto\tmake\ta\tbomb", "DC-001", PolicyAction.BLOCK),
    ("how-to-make-a-bomb", "DC-001", PolicyAction.BLOCK),
    ("how\u00a0to\u00a0make\u00a0a\u00a0bomb", "DC-001", PolicyAction.BLOCK),
    ("legal\u2003advice", "HAC-001", PolicyAction.REQUIRE_HUMAN),
    ("legal_advice", "HAC-001", PolicyAction.REQUIRE_HUMAN),
    ("lega\u200bl advice", "HAC-001", PolicyAction.REQUIRE_HUMAN),
    ("legal\u200badvice", "HAC-001", PolicyAction.REQUIRE_HUMAN),
    ("l\u0435gal advice", "HAC-001", PolicyAction.REQUIRE_HUMAN),            # Cyrillic e
    ("someone\u2019s password", "DP-001", PolicyAction.BLOCK),
    ("someones password", "DP-001", PolicyAction.BLOCK),
    ("don\u2019t ask me to confirm", "HAC-002", PolicyAction.FLAG),
    ("dont ask me to confirm", "HAC-002", PolicyAction.FLAG),
    ("don\u00b4t ask me to confirm", "HAC-002", PolicyAction.FLAG),
    ("home\taddress", "DP-002", PolicyAction.FLAG),
    ("SOCIAL\tSECURITY\tNUMBER", "DP-001", PolicyAction.BLOCK),
])
def test_a_rule_matches_through_a_view(engine, raw, rule, action):
    flags, most = run(engine, raw)
    assert rule in ids(flags) and most == action


def test_without_views_the_same_inputs_are_not_matched_which_proves_the_views_did_it(engine):
    for raw, rule in [("how\tto\tmake\ta\tbomb", "DC-001"), ("legal_advice", "HAC-001")]:
        s = screen_request(raw)
        assert rule not in ids(engine.evaluate(s.normalized_text)[0])
        assert rule in ids(engine.evaluate(s.normalized_text, match_views=s.match_views)[0])


def test_no_views_is_identical_to_v1_for_plain_text(engine):
    for text in ["what's a good recipe", "how to make a bomb at home", "I need legal advice", "weapon"]:
        assert engine.evaluate(text, None) == engine.evaluate(text)


def test_several_rules_still_combine_to_the_most_severe(engine):
    flags, most = run(engine, "legal_advice and how\tto\tmake\ta\tbomb")
    assert {"HAC-001", "DC-001"} <= ids(flags) and most == PolicyAction.BLOCK


# ---- v1 result is preserved: views only ADD ----

@pytest.mark.parametrize("text", ["how to make a bomb", "I need legal advice", "personal data", "weapon",
                                  "don't ask me to confirm", "someone's password", "ssn: 123"])
def test_every_v1_match_survives_when_views_are_supplied(engine, text):
    v1_flags, v1_action = engine.evaluate(text)
    flags, action = engine.evaluate(text, match_views=build_match_views(text))
    assert ids(v1_flags) <= ids(flags) and action == v1_action


def test_v1_match_is_kept_when_the_view_step_raises(engine, monkeypatch):
    def boom(rule, view_texts):
        raise RuntimeError("view step broke")
    monkeypatch.setattr(engine, "_view_match", boom)
    # DC-001 matches in v1 so the broken view step is never reached for it; other rules with no v1 match
    # reach the view step and follow THEIR failure mode (closed for most).
    s = screen_request("how to make a bomb")
    flags, action = engine.evaluate(s.normalized_text, match_views=s.match_views)
    dc1 = [f for f in flags if f.rule_id == "DC-001"]
    assert len(dc1) == 1 and dc1[0].reason == "Instructions to cause physical harm or build weapons"
    assert action == PolicyAction.BLOCK


# ---- failures follow failure_modes.yaml ----

def test_a_view_failure_fails_closed_for_a_fail_closed_rule(engine, monkeypatch):
    monkeypatch.setattr(engine, "_view_match", lambda rule, v: (_ for _ in ()).throw(RuntimeError("x")))
    s = screen_request("a harmless question about gardening")
    flags, action = engine.evaluate(s.normalized_text, match_views=s.match_views)
    closed = {r["rule_id"] for r in engine._rules if engine._fail_closed_for(r["rule_id"])}
    assert ids(flags) == closed and action == PolicyAction.BLOCK
    assert all("failed closed" in f.reason for f in flags)


def test_a_view_failure_fails_open_for_a_fail_open_rule(engine, monkeypatch):
    def only_dc2(rule, v):
        if rule["rule_id"] == "DC-002":
            raise RuntimeError("x")
        return False
    monkeypatch.setattr(engine, "_view_match", only_dc2)
    s = screen_request("a harmless question about gardening")
    flags, action = engine.evaluate(s.normalized_text, match_views=s.match_views)
    assert flags == [] and action == PolicyAction.ALLOW


# ---- wrong types are wiring bugs ----

@pytest.mark.parametrize("bad", ["a string", 5, ["a"], {"flat_strip": "x"}, b"x"])
def test_a_wrong_type_raises_instead_of_silently_matching_v1_only(engine, bad):
    with pytest.raises(TypeError):
        engine.evaluate("hello", match_views=bad)


def test_none_and_a_real_matchviews_are_the_only_accepted_values(engine):
    engine.evaluate("hello", match_views=None)
    engine.evaluate("hello", match_views=MatchViews("hello", "hello", "hello"))


# ---- canonical keywords ----

def test_an_empty_canonical_keyword_is_skipped_and_never_matches_everything(engine):
    rule = {"rule_id": "X-1", "risk_category": "data_privacy", "action": "flag", "keywords": ["'", " - ", "legal advice"]}
    engine._rules = [rule]
    assert engine._canonical(("'", " - ", "legal advice")) == ("legal advice",)
    flags, _ = engine.evaluate("harmless", match_views=build_match_views("harmless"))
    assert flags == []


def test_a_rule_with_only_an_empty_canonical_keyword_matches_nothing_through_views(engine):
    engine._rules = [{"rule_id": "X-2", "risk_category": "data_privacy", "action": "flag", "keywords": ["'"]}]
    flags, _ = engine.evaluate("anything", match_views=build_match_views("anything"))
    assert flags == []


def test_canonical_keywords_are_memoised_per_keyword_tuple(engine):
    kws = ("legal advice", "medical diagnosis")
    assert engine._canonical(kws) is engine._canonical(kws)


def test_a_rule_without_keywords_does_not_break_the_view_step(engine):
    engine._rules = [{"rule_id": "X-3", "risk_category": "data_privacy", "action": "flag"}]
    assert engine.evaluate("hello", match_views=build_match_views("hello")) == ([], PolicyAction.ALLOW)


# ---- benign requests stay benign through the views ----

@pytest.mark.parametrize("raw", [
    "What's a good recipe for banana bread?",
    "Summarise this state-of-the-art e-mail for me",
    "Can you help me write a thank-you note to my neighbour?",
    "I don't want to be late. Is the 8:15 train fast?",
    "Explain how a bill becomes law in the US",
])
def test_benign_requests_get_no_flag_through_the_views(engine, raw):
    assert run(engine, raw) == ([], PolicyAction.ALLOW)
