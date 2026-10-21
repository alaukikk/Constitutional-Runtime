
import dataclasses
import json

import pytest

from evaluation import golden_set as gs

ITEMS = gs.load()


def _item(**over):
    base = dataclasses.asdict(ITEMS[0])
    base["expected_rules"] = list(base["expected_rules"])
    base["tags"] = list(base["tags"])
    base.update(over)
    return gs.item_from_dict(base)


def test_committed_set_is_well_formed():
    assert gs.problems(ITEMS) == []


def test_carries_forward_the_informal_sets():
    texts = {i.text for i in ITEMS}
    for t in ("what is the capital of Japan", "2 + 2", "I need legal advice about my divorce",
              "what is the best medical diagnosis for chest pain"):
        assert t in texts
    assert len(ITEMS) >= 17


def test_claude_drafts_are_never_presented_as_reviewed_or_frozen():
    assert all(i.labeler == "claude-draft" for i in ITEMS)      # until the owner relabels
    assert all(i.review == "draft" and i.split == "dev" for i in ITEMS)
    assert len(gs.unreviewed(ITEMS)) == len(ITEMS)


def test_every_item_has_rationale_and_origin():
    assert all(i.rationale.strip() and i.origin.strip() for i in ITEMS)


def test_contested_items_are_visible_and_policy_gaps_are_contested():
    contested = {i.id for i in ITEMS if "contested" in i.tags}
    assert "G-017" in contested
    gaps = {i.id for i in ITEMS if "policy_gap" in i.tags}
    assert gaps and gaps <= contested            # a recall gap is an owner decision until settled


def test_set_covers_every_type_tier_and_gate():
    from policy.schemas import MethodTier, RequestType
    assert {i.true_type for i in ITEMS} == {t.value for t in RequestType}
    tiers = {i.cheapest_adequate_tier for i in ITEMS}
    for t in (MethodTier.DETERMINISTIC, MethodTier.SMALL_CLASSIFIER,
              MethodTier.RAG_SMALL_MODEL, MethodTier.LLM_LOW_REASONING):
        assert t.value in tiers
    assert {i.expected_gate for i in ITEMS} == set(gs.GATES)


def test_every_policy_rule_is_exercised_by_at_least_one_item():
    from collections import Counter
    seen = Counter(r for i in ITEMS for r in i.expected_rules)
    assert set(seen) == set(gs._rule_actions())


def test_set_includes_benign_lookalikes_and_known_limits():
    tags = {t for i in ITEMS for t in i.tags}
    assert {"benign_sensitive_word", "known_limit", "oi_086", "oi_087", "oi_089",
            "unsupported_script", "stage0_suspicious", "keyword_dilution"} <= tags
    benign = [i for i in ITEMS if "benign_sensitive_word" in i.tags]
    assert len(benign) >= 8 and all(i.expected_gate == "allow" for i in benign)


def test_set_is_large_enough_to_report_per_class_but_not_claimed_representative():
    assert 100 <= len(ITEMS) <= 200


def test_labels_are_not_just_the_current_classifier_output():
    """The set must be able to fail: at least one label disagrees with today's classifier."""
    from triage.classifier import classify
    disagreements = [i.id for i in ITEMS if classify(i.text).category.value != i.true_type]
    assert disagreements, "golden set is circular: it only encodes what the classifier already does"


@pytest.mark.parametrize("over,needle", [
    ({"id": "X-1"}, "id must look like"),
    ({"true_type": "nonsense"}, "unknown true_type"),
    ({"cheapest_adequate_tier": "magic"}, "unknown tier"),
    ({"expected_gate": "maybe"}, "unknown gate"),
    ({"expected_rules": ["NOPE-9"]}, "not in config/constitution.yaml"),
    ({"expected_rules": ["HAC-001"], "expected_gate": "allow"}, "its rules give require_human"),
    ({"expected_gate": "block"}, "needs expected_rules"),
    ({"rationale": " "}, "rationale and origin are required"),
    ({"review": "owner_reviewed"}, "cannot be marked owner_reviewed"),
    ({"split": "frozen"}, "frozen items must be owner_reviewed"),
    ({"text": "  "}, "empty text"),
    ({"true_type": "generation", "cheapest_adequate_tier": "deterministic"}, "cannot be adequately answered below"),
])
def test_integrity_rules_reject_bad_items(over, needle):
    assert any(needle in p for p in gs.problems([_item(**over)]))


def test_frozen_contested_item_rejected():
    bad = _item(labeler="owner", review="owner_reviewed", split="frozen", tags=["contested"])
    assert any("contested" in p for p in gs.problems([bad]))


def test_gated_request_cannot_be_deterministic():
    bad = _item(expected_gate="require_human", expected_rules=["HAC-001"],
                cheapest_adequate_tier="deterministic", true_type="lookup")
    assert any("cache/deterministic" in p for p in gs.problems([bad]))


def test_duplicate_text_after_normalization_and_duplicate_id():
    a = _item()
    b = _item(id="G-099", text="  " + a.text.upper() + "  ")
    assert any("same text as" in p for p in gs.problems([a, b]))
    assert any("duplicate id" in p for p in gs.problems([a, a]))


def test_loader_rejects_unknown_and_missing_fields(tmp_path):
    row = dataclasses.asdict(ITEMS[0])
    row["expected_rules"], row["tags"] = [], []
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({**row, "surprise": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected"):
        gs.load(p)
    del row["rationale"]
    p.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        gs.load(p)


def test_fingerprint_is_order_insensitive_and_covers_every_label_field():
    base = gs.fingerprint(ITEMS)
    assert gs.fingerprint(list(reversed(ITEMS))) == base
    for over in ({"true_type": "unknown"}, {"cheapest_adequate_tier": "llm_high_reasoning"},
                 {"expected_gate": "flag", "expected_rules": ["DC-002"]}):
        changed = [_item(**over)] + ITEMS[1:]
        assert gs.fingerprint(changed) != base
