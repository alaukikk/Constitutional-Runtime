
"""Golden set for the Sprint 7-8 experiment (OI-011): schema, loader, integrity rules.

What this is: a labeled set of requests whose labels say what the RIGHT treatment is,
independent of what the current implementation does. Items the runtime gets wrong are
the point; the set must be able to fail. (The informal sets in tests/triage/ were
derived from classifier behaviour, so they can only pass. They are carried forward
here with labels re-stated from the request itself.)

Label fields (all judgment; see ``rationale`` on each item):
  true_type               RequestType the request really is.
  cheapest_adequate_tier  Cheapest MethodTier that would answer it ADEQUATELY, regardless
                          of which tiers are implemented today. Project rule: a cheap tier
                          is only adequate where a wrong answer is low-cost (see
                          triage/taxonomy.py CHEAP_TIER_ELIGIBLE).
  expected_gate           allow | flag | require_human | block: the outcome the constitution
                          should reach for this request.
  expected_rules          policy rule ids that should fire (may be empty).
                          Tag 'stage0': the Stage 0 screen should refuse it (no rule id).
                          Tag 'policy_gap': the constitution SHOULD gate it but no rule covers it
                          today (a recall gap; also 'contested' until the owner settles it).
  For a refused request (gate block) cheapest_adequate_tier is a placeholder and is not scored.

Provenance (never dropped, never upgraded silently):
  labeler   "claude-draft" or "owner". Claude's labels are drafts, not ground truth.
  review    "draft" or "owner_reviewed". Only the owner moves an item to owner_reviewed.
  split     "dev" or "frozen". A frozen item must be owner_reviewed. Freeze BEFORE any
            threshold is tuned (audit/metrics.py), and record ``fingerprint()``.

Limits stated on purpose: a small hand-written set measures the cases written, not
real traffic (shadow mode does that); labels for contested items (tag ``contested``)
are policy judgments the owner must settle before they count as evidence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml

from audit.metrics import dataset_fingerprint
from policy.schemas import MethodTier, PolicyAction, RequestType

DATA_PATH = Path(__file__).resolve().parent / "data" / "golden_v1.jsonl"
_CONSTITUTION = Path(__file__).resolve().parents[1] / "config" / "constitution.yaml"

LABELERS = ("claude-draft", "owner")
REVIEWS = ("draft", "owner_reviewed")
SPLITS = ("dev", "frozen")
GATES = tuple(a.value for a in PolicyAction)
_ID_RE = re.compile(r"^G-\d{3}$")
_GATE_ORDER = {"allow": 0, "flag": 1, "require_human": 2, "block": 3}

# Tiers that may be "adequate" for a type. Mirrors the project rule that a wrong cheap answer
# must be low-cost; HIGH_STAKES, GENERATION and JUDGMENT need a model.
_LLM_TIERS = {MethodTier.LLM_LOW_REASONING.value, MethodTier.LLM_HIGH_REASONING.value}
_MODEL_ONLY_TYPES = {RequestType.HIGH_STAKES.value, RequestType.GENERATION.value,
                     RequestType.JUDGMENT.value}


@dataclass(frozen=True)
class GoldenItem:
    id: str
    text: str
    true_type: str
    cheapest_adequate_tier: str
    expected_gate: str
    expected_rules: tuple[str, ...]
    tags: tuple[str, ...]
    origin: str
    rationale: str
    labeler: str
    review: str
    split: str

    def label(self) -> str:
        """Canonical label string used for fingerprinting (every label field, not only the type)."""
        return json.dumps(
            [self.true_type, self.cheapest_adequate_tier, self.expected_gate,
             sorted(self.expected_rules)], separators=(",", ":"))


def _rule_actions() -> dict[str, str]:
    with open(_CONSTITUTION, encoding="utf-8") as fh:
        return {r["rule_id"]: r["action"] for r in yaml.safe_load(fh)["rules"]}


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def item_from_dict(d: dict) -> GoldenItem:
    required = {"id", "text", "true_type", "cheapest_adequate_tier", "expected_gate",
                "expected_rules", "tags", "origin", "rationale", "labeler", "review", "split"}
    missing, extra = required - d.keys(), d.keys() - required
    if missing or extra:
        raise ValueError(f"item {d.get('id', '?')}: missing {sorted(missing)} unexpected {sorted(extra)}")
    for key in ("expected_rules", "tags"):
        if not isinstance(d[key], list) or not all(isinstance(x, str) for x in d[key]):
            raise ValueError(f"item {d['id']}: {key} must be a list of strings")
    for key in required - {"expected_rules", "tags"}:
        if not isinstance(d[key], str):
            raise ValueError(f"item {d['id']}: {key} must be a string")
    return GoldenItem(**{**d, "expected_rules": tuple(d["expected_rules"]), "tags": tuple(d["tags"])})


def load(path: Optional[Path] = None) -> list[GoldenItem]:
    p = Path(path) if path else DATA_PATH
    items = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                items.append(item_from_dict(json.loads(line)))
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{p.name} line {n}: {exc}") from None
    return items


def problems(items: Iterable[GoldenItem]) -> list[str]:
    """Every integrity violation, as readable strings. Empty list means the set is well-formed
    (not that the labels are right)."""
    out: list[str] = []
    actions = _rule_actions()
    ids, texts = set(), {}
    for it in items:
        w = f"{it.id}"
        if not _ID_RE.match(it.id):
            out.append(f"{w}: id must look like G-001")
        if it.id in ids:
            out.append(f"{w}: duplicate id")
        ids.add(it.id)
        key = _norm(it.text)
        if not key:
            out.append(f"{w}: empty text (empty input is a Stage 0 case, not a routing case)")
        if key in texts:
            out.append(f"{w}: same text as {texts[key]} after whitespace/case normalization")
        texts[key] = it.id
        if it.true_type not in {t.value for t in RequestType}:
            out.append(f"{w}: unknown true_type {it.true_type!r}")
        if it.cheapest_adequate_tier not in {t.value for t in MethodTier}:
            out.append(f"{w}: unknown tier {it.cheapest_adequate_tier!r}")
        if it.expected_gate not in GATES:
            out.append(f"{w}: unknown gate {it.expected_gate!r}")
        if it.labeler not in LABELERS:
            out.append(f"{w}: unknown labeler {it.labeler!r}")
        if it.review not in REVIEWS:
            out.append(f"{w}: unknown review {it.review!r}")
        if it.split not in SPLITS:
            out.append(f"{w}: unknown split {it.split!r}")
        if not it.rationale.strip() or not it.origin.strip():
            out.append(f"{w}: rationale and origin are required (traceability)")
        if it.labeler == "claude-draft" and it.review == "owner_reviewed":
            out.append(f"{w}: a claude-draft label cannot be marked owner_reviewed; relabel as owner")
        if it.split == "frozen" and it.review != "owner_reviewed":
            out.append(f"{w}: frozen items must be owner_reviewed")
        if it.split == "frozen" and "contested" in it.tags:
            out.append(f"{w}: a contested item must be settled (tag removed) before it can be frozen")
        for rid in it.expected_rules:
            if rid not in actions:
                out.append(f"{w}: expected rule {rid} is not in config/constitution.yaml")
        known = [actions[r] for r in it.expected_rules if r in actions]
        if known:
            worst = max(known, key=_GATE_ORDER.__getitem__)
            if it.expected_gate != worst:
                out.append(f"{w}: expected_gate {it.expected_gate} but its rules give {worst}")
        elif it.expected_gate != "allow" and not ({"stage0", "policy_gap"} & set(it.tags)):
            out.append(f"{w}: gate {it.expected_gate} needs expected_rules, or the tag 'stage0' or 'policy_gap'")
        if it.true_type in _MODEL_ONLY_TYPES and it.cheapest_adequate_tier not in _LLM_TIERS:
            out.append(f"{w}: {it.true_type} cannot be adequately answered below an LLM tier")
        if it.expected_gate in ("require_human", "block") and it.cheapest_adequate_tier in (
                MethodTier.CACHE.value, MethodTier.DETERMINISTIC.value):
            out.append(f"{w}: a gated request cannot be adequately answered by cache/deterministic")
    return out


def fingerprint(items: Iterable[GoldenItem]) -> str:
    """Order-insensitive SHA-256 over (text, every label). Record it when the set is frozen."""
    return dataset_fingerprint([(i.text, i.label()) for i in items])


def unreviewed(items: Iterable[GoldenItem]) -> list[GoldenItem]:
    return [i for i in items if i.review != "owner_reviewed"]
