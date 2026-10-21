
"""Offline scoring of the CURRENT runtime against the golden set (Sprint 7-8, step 1 of 5).

Runs the real Stage 0 screen, Stage 1 policy engine, Stage 3 classifier and planner, and the
deterministic tier on each golden item. No model call, no network, no session state, no tuning:
it only measures. It changes no threshold and writes nothing unless a path is passed.

What it can and cannot say (read before quoting any number):
  * Labels are Claude drafts until the owner reviews them (evaluation/golden_set.py). While any
    item is unreviewed or the split is not frozen, every figure is DIAGNOSTIC, not evidence.
  * The set is small and hand-written; it measures the cases written, not real traffic.
  * It scores gates, classification and routing structure. It does NOT score answer quality
    (needs real LLM integration), cache behaviour (needs state), latency, or energy (inputs are
    placeholders, OI-005), so none of those appear here.
  * Stage 3 classification and planning use Stage 0's normalized text, as the pipeline does.

Definitions (n = items scored in that section):
  classifier agreement   classify(text).category == true_type. Per-type precision/recall.
  gate agreement         Stage 0 BLOCKED -> block; otherwise the most severe Stage 1 action.
                         false_negative = actual less severe than expected (the costly side);
                         false_positive = actual more severe than expected.
  rule recall            expected rules that fired / expected rules. Extra rules fired are counted
                         separately (they are not errors by themselves).
  missed_saving          cheapest adequate tier is below the LLM but is not on the planned ladder,
                         so the request is forced up to a costlier tier.
  unsafe_cheap_path      a request that needs a model (high_stakes / generation / judgment) has the
                         small-classifier or RAG rung on its ladder.
  deterministic gap      cheapest adequate tier is deterministic but try_deterministic() declines.
  deterministic overreach  try_deterministic() answers an item whose adequate tier is NOT
                         deterministic. Answer CORRECTNESS is not checked (no expected answers).
Routing is scored only for items the gate lets through (gate != block).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from evaluation import golden_set as gs
from guardrails.injection_screen import ScreenVerdict, screen_request
from policy.engine import get_policy_engine
from policy.schemas import MethodTier, RequestType
from tiers.deterministic import try_deterministic
from triage.classifier import classify
from triage.decision import plan_request

_SEV = {"allow": 0, "flag": 1, "require_human": 2, "block": 3}
_MODEL_ONLY = {RequestType.HIGH_STAKES.value, RequestType.GENERATION.value, RequestType.JUDGMENT.value}
_MID_MODEL_TIERS = {MethodTier.SMALL_CLASSIFIER.value, MethodTier.RAG_SMALL_MODEL.value}
_LLM_TIERS = {MethodTier.LLM_LOW_REASONING.value, MethodTier.LLM_HIGH_REASONING.value}


@dataclass
class ItemResult:
    id: str
    text: str
    tags: tuple[str, ...]
    expected_gate: str
    actual_gate: str
    gate_error: str                     # "" | "false_negative" | "false_positive"
    stage0: str
    fired_rules: tuple[str, ...]
    rules_missing: tuple[str, ...]
    rules_extra: tuple[str, ...]
    classified_as: Optional[str]        # None when the gate refused the request
    classifier_ok: Optional[bool]
    attempt_order: Optional[tuple[str, ...]]
    missed_saving: Optional[bool]
    unsafe_cheap_path: Optional[bool]
    det_gap: Optional[bool]
    det_overreach: Optional[bool]


def _gate(text: str):
    sr = screen_request(text)
    if sr.verdict == ScreenVerdict.BLOCKED:
        return sr, "block", ()
    flags, severest = get_policy_engine().evaluate(sr.normalized_text, match_views=sr.match_views)
    return sr, severest.value, tuple(sorted({f.rule_id for f in flags}))


def score_item(item: gs.GoldenItem) -> ItemResult:
    sr, gate, fired = _gate(item.text)
    err = ""
    if _SEV[gate] < _SEV[item.expected_gate]:
        err = "false_negative"
    elif _SEV[gate] > _SEV[item.expected_gate]:
        err = "false_positive"
    expected = set(item.expected_rules)
    res = dict(
        id=item.id, text=item.text, tags=item.tags, expected_gate=item.expected_gate, actual_gate=gate,
        gate_error=err, stage0=sr.verdict.value, fired_rules=fired,
        rules_missing=tuple(sorted(expected - set(fired))), rules_extra=tuple(sorted(set(fired) - expected)),
        classified_as=None, classifier_ok=None, attempt_order=None, missed_saving=None,
        unsafe_cheap_path=None, det_gap=None, det_overreach=None)
    if gate != "block":
        text = sr.normalized_text
        cls = classify(text).category.value
        order = tuple(t.value for t in plan_request(text).attempt_order)
        det_answers = try_deterministic(text) is not None
        adequate = item.cheapest_adequate_tier
        res.update(
            classified_as=cls, classifier_ok=(cls == item.true_type), attempt_order=order,
            missed_saving=(adequate not in _LLM_TIERS and adequate not in order),
            unsafe_cheap_path=(item.true_type in _MODEL_ONLY and bool(_MID_MODEL_TIERS & set(order))),
            det_gap=(adequate == MethodTier.DETERMINISTIC.value and not det_answers),
            det_overreach=(adequate != MethodTier.DETERMINISTIC.value and det_answers))
    return ItemResult(**res)


def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def evaluate(items: Iterable[gs.GoldenItem]) -> dict:
    items = list(items)
    results = [score_item(i) for i in items]
    by_id = {i.id: i for i in items}

    routed = [r for r in results if r.classified_as is not None]
    per_type: dict[str, dict] = {}
    for t in sorted({i.true_type for i in items}):
        support = [r for r in routed if by_id[r.id].true_type == t]
        predicted = [r for r in routed if r.classified_as == t]
        tp = sum(1 for r in support if r.classifier_ok)
        per_type[t] = {"support": len(support), "predicted": len(predicted), "true_positive": tp,
                       "recall": _rate(tp, len(support)), "precision": _rate(tp, len(predicted))}
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in routed:
        confusion[by_id[r.id].true_type][r.classified_as] += 1

    gate_conf: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        gate_conf[r.expected_gate][r.actual_gate] += 1

    rules: dict[str, dict] = {}
    for rid in sorted({x for i in items for x in i.expected_rules}):
        exp = [r for r in results if rid in by_id[r.id].expected_rules]
        rules[rid] = {"expected": len(exp), "fired": sum(1 for r in exp if rid in r.fired_rules)}
        rules[rid]["recall"] = _rate(rules[rid]["fired"], rules[rid]["expected"])

    s0_susp = [r for r in results if "stage0_suspicious" in r.tags]
    tag_table: dict[str, dict] = {}
    for tag in sorted({t for i in items for t in i.tags}):
        sub = [r for r in results if tag in r.tags]
        tag_table[tag] = {"n": len(sub),
                          "gate_disagreements": sum(1 for r in sub if r.gate_error),
                          "classifier_disagreements": sum(1 for r in sub if r.classifier_ok is False)}

    def count(field_name: str) -> int:
        return sum(1 for r in routed if getattr(r, field_name))

    prov = {"items": len(items),
            "labelers": dict(Counter(i.labeler for i in items)),
            "reviews": dict(Counter(i.review for i in items)),
            "splits": dict(Counter(i.split for i in items)),
            "contested": sum(1 for i in items if "contested" in i.tags),
            "fingerprint": gs.fingerprint(items) if items else None}
    diagnostic = bool(gs.unreviewed(items)) or any(i.split != "frozen" for i in items)

    return {
        "diagnostic_only": diagnostic,
        "provenance": prov,
        "gate": {"n": len(results),
                 "exact_agreement": _rate(sum(1 for r in results if not r.gate_error), len(results)),
                 "false_negatives": sum(1 for r in results if r.gate_error == "false_negative"),
                 "false_positives": sum(1 for r in results if r.gate_error == "false_positive"),
                 "confusion": {k: dict(v) for k, v in gate_conf.items()},
                 "stage0_suspicious_expected": len(s0_susp),
                 "stage0_suspicious_got": sum(1 for r in s0_susp if r.stage0 == "suspicious"),
                 "rules": rules},
        "classifier": {"n": len(routed),
                       "agreement": _rate(sum(1 for r in routed if r.classifier_ok), len(routed)),
                       "per_type": per_type,
                       "confusion": {k: dict(v) for k, v in confusion.items()}},
        "routing": {"n": len(routed), "missed_saving": count("missed_saving"),
                    "unsafe_cheap_path": count("unsafe_cheap_path"),
                    "deterministic_gap": count("det_gap"),
                    "deterministic_overreach": count("det_overreach")},
        "by_tag": tag_table,
        "misses": [asdict(r) for r in results
                   if r.gate_error or r.classifier_ok is False or r.missed_saving
                   or r.unsafe_cheap_path or r.det_gap or r.det_overreach],
    }


def _short(text: str, n: int = 60) -> str:
    s = ascii(text)[1:-1]
    return s if len(s) <= n else s[: n - 3] + "..."


def render_markdown(rep: dict) -> str:
    p, g, c, ro = rep["provenance"], rep["gate"], rep["classifier"], rep["routing"]
    L = ["# Golden set: offline run of the current runtime", ""]
    if rep["diagnostic_only"]:
        L += ["> **DIAGNOSTIC ONLY.** Labels are unreviewed drafts and/or the set is not frozen. "
              "Do not quote these figures as evidence of any property.", ""]
    L += [f"Items {p['items']}; labelers {p['labelers']}; reviews {p['reviews']}; splits {p['splits']}; "
          f"contested {p['contested']}.", f"Fingerprint `{p['fingerprint']}`.", "",
          "Not measured here: answer quality, cache behaviour, latency, energy.", "",
          "## Gates", f"- exact agreement {g['exact_agreement']} over {g['n']}; "
          f"false negatives {g['false_negatives']}, false positives {g['false_positives']}",
          f"- Stage 0 suspicious: expected {g['stage0_suspicious_expected']}, got {g['stage0_suspicious_got']}"]
    for rid, v in g["rules"].items():
        L.append(f"- {rid}: recall {v['recall']} ({v['fired']}/{v['expected']})")
    L += ["", "## Classifier", f"- agreement {c['agreement']} over {c['n']} routed items", "",
          "| true type | support | predicted | recall | precision |", "|---|---|---|---|---|"]
    for t, v in c["per_type"].items():
        L.append(f"| {t} | {v['support']} | {v['predicted']} | {v['recall']} | {v['precision']} |")
    L += ["", "## Routing structure",
          f"- missed savings {ro['missed_saving']}, unsafe cheap path {ro['unsafe_cheap_path']}, "
          f"deterministic gaps {ro['deterministic_gap']}, deterministic overreach {ro['deterministic_overreach']} "
          f"(over {ro['n']} routed items)", "", "## Misses", "| id | text | tags | issue |", "|---|---|---|---|"]
    for m in rep["misses"]:
        issues = [x for x, on in (("gate " + m["gate_error"] + f" ({m['expected_gate']}->{m['actual_gate']})", m["gate_error"]),
                                  ("classified " + str(m["classified_as"]), m["classifier_ok"] is False),
                                  ("missed saving", m["missed_saving"]), ("unsafe cheap path", m["unsafe_cheap_path"]),
                                  ("deterministic gap", m["det_gap"]), ("deterministic overreach", m["det_overreach"])) if on]
        L.append(f"| {m['id']} | {_short(m['text'])} | {', '.join(m['tags'])} | {'; '.join(issues)} |")
    return "\n".join(L) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=("dev", "frozen", "all"), default="all")
    ap.add_argument("--json", type=Path, help="write the full report as JSON")
    ap.add_argument("--markdown", type=Path, help="write the readable report")
    a = ap.parse_args(argv)
    items = [i for i in gs.load() if a.split == "all" or i.split == a.split]
    bad = gs.problems(items)
    if bad:
        print("golden set is not well-formed:\n" + "\n".join(bad), file=sys.stderr)
        return 2
    rep = evaluate(items)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2, sort_keys=True, default=list), encoding="utf-8")
    md = render_markdown(rep)
    if a.markdown:
        a.markdown.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
