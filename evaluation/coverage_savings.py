"""Coverage-vs-savings ceiling from the draft taxonomy labels (OI-097, OI-098).

Reads golden_v1.jsonl and taxonomy_labels_v1_draft.jsonl (both draft) and, for the items that are
not Stage 0/1 gate tests, orders the handler groups by how many items each could take off the LLM
and prints a cumulative curve. Handler groups are the taxonomy subcategories whose solver is not an
LLM (key-value table, arithmetic, unit conversion, string transform, classifier, retrieval).

What this is: a CEILING and an ordering. It counts requests a handler could answer if it existed
and were correct. It builds nothing and measures nothing.
What it is not: a savings measurement. Token figures multiply the item count by ``--tokens-per-call``
(default 141, the mean provider-reported tokens of the calls the runtime avoided in the first
diagnostic run; the all-baseline mean was 309.4). Change it to see the sensitivity. No energy or
dollar figure (OI-005). Draft labels, 106 hand-picked items, so the shares say nothing about real
traffic.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "data"
NON_LLM = {"deterministic", "small_classifier", "rag_small_model"}


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def curve(labels, tokens_per_call):
    pool = [r for r in labels if r["section"] != "n/a"]
    groups = Counter(
        (r["taxonomy_tier"], r["section"], r["subcategory"]) for r in pool if r["taxonomy_tier"] in NON_LLM
    )
    rows, cum = [], 0
    # Cheapest tier first, then largest group: mirrors the ladder, and builds the cheap handlers first.
    order = {"deterministic": 0, "small_classifier": 1, "rag_small_model": 2}
    for (tier, sec, sub), n in sorted(groups.items(), key=lambda kv: (order[kv[0][0]], -kv[1])):
        cum += n
        rows.append(dict(tier=tier, section=sec, subcategory=sub, items=n, cumulative=cum,
                         share=cum / len(pool), tokens=cum * tokens_per_call))
    return len(pool), rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tokens-per-call", type=float, default=141.0)
    ap.add_argument("--labels", default=str(DATA / "taxonomy_labels_v1_draft.jsonl"))
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args(argv)
    labels = load(a.labels)
    n, rows = curve(labels, a.tokens_per_call)
    print("DIAGNOSTIC CEILING, draft labels, not a measurement.")
    print(f"Non-gate items: {n}. Tokens assumed per avoided call: {a.tokens_per_call:g}.\n")
    hdr = ["Handler group (cheapest tier first)", "Items", "Cumulative", "Share of non-gate", "Tokens (assumed)"]
    out = [hdr] + [[f"{r['tier']}: {r['section']} {r['subcategory']}", r["items"], r["cumulative"],
                    f"{r['share']:.1%}", f"{r['tokens']:.0f}"] for r in rows]
    if a.markdown:
        print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
        for o in out[1:]:
            print("| " + " | ".join(str(x) for x in o) + " |")
    else:
        for o in out:
            print(" | ".join(str(x) for x in o))
    print("\nUpper bound only: every listed handler built and correct. Tokens = items x assumed per-call tokens.")


if __name__ == "__main__":
    main()
