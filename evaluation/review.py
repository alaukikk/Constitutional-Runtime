
"""Owner review sheet for the golden set (OI-011).

Flow: ``export`` writes a CSV the owner opens in a spreadsheet; the owner fills the ``decision``
column; ``apply`` turns those decisions into a new reviewed JSONL. Nothing is written in place.

Design choices, on purpose:
  * The sheet shows the request, Claude's draft labels, tags and rationale. It does NOT show what
    the current runtime does with the item. Seeing the system's answer would pull labels toward
    the system's behaviour, which is the circularity this set exists to avoid.
  * decision values: ``agree`` (keep the draft labels), ``change`` (use the non-blank ``new_*``
    cells), blank or ``skip`` (item stays a draft). Anything else is an error, not a guess.
  * Agree/change makes the item ``labeler=owner`` and ``review=owner_reviewed``: "owner" means
    the owner adopted the label. The draft origin stays in ``origin``.
  * A ``contested`` item cannot be agreed or changed unless ``contested_resolved`` is ``yes``;
    that removes the tag. Settling a policy question is the owner's call and is never implied.
  * The text column shows non-printable and non-ASCII characters as \\uXXXX escapes so invisible
    characters are visible; ``apply`` never edits an item's text.
  * ``apply`` re-runs every integrity rule on the result and refuses to output a malformed set.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

from evaluation import golden_set as gs

COLUMNS = ["id", "text_display", "tags", "rationale", "true_type", "cheapest_adequate_tier",
           "expected_gate", "expected_rules", "decision", "new_true_type", "new_tier", "new_gate",
           "new_rules", "contested_resolved", "note"]
DECISIONS = {"", "skip", "agree", "change"}


class ReviewError(ValueError):
    """Sheet could not be applied. ``problems`` holds one readable line per bad row (ids and rule
    names only); callers print that list, never the exception object (OI-084 guard)."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def display(text: str) -> str:
    def one(c: str) -> str:
        if c == "\n":
            return "\\n"
        if c.isascii() and c.isprintable():
            return c
        return f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}"

    return "".join(one(c) for c in text)


def export_sheet(items: Iterable[gs.GoldenItem], path: Path) -> int:
    n = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for it in items:
            w.writerow({"id": it.id, "text_display": display(it.text), "tags": ";".join(it.tags),
                        "rationale": it.rationale, "true_type": it.true_type,
                        "cheapest_adequate_tier": it.cheapest_adequate_tier,
                        "expected_gate": it.expected_gate, "expected_rules": ";".join(it.expected_rules)})
            n += 1
    return n


def _rules(cell: str) -> list[str]:
    return [r.strip() for r in cell.replace(",", ";").split(";") if r.strip()]


def check_decisions(items: list[gs.GoldenItem], rows: list[dict]):
    """Pure, non-raising. Returns (new items or None, counts, problems). Items are None when problems is non-empty."""
    by_id = {i.id: i for i in items}
    errors: list[str] = []
    new = dict(by_id)
    counts = {"agree": 0, "change": 0, "skip": 0}
    seen: set[str] = set()
    for row in rows:
        rid = (row.get("id") or "").strip()
        dec = (row.get("decision") or "").strip().lower()
        if rid not in by_id:
            errors.append(f"{rid or '(blank id)'}: not in the golden set")
            continue
        if rid in seen:
            errors.append(f"{rid}: appears twice in the sheet")
            continue
        seen.add(rid)
        if dec not in DECISIONS:
            errors.append(f"{rid}: decision {dec!r} must be agree, change or blank")
            continue
        if dec in ("", "skip"):
            counts["skip"] += 1
            continue
        it = by_id[rid]
        tags = list(it.tags)
        if "contested" in tags:
            if (row.get("contested_resolved") or "").strip().lower() != "yes":
                errors.append(f"{rid}: contested; set contested_resolved=yes only if you have settled it")
                continue
            tags.remove("contested")
        changes: dict = {}
        if dec == "change":
            for col, field in (("new_true_type", "true_type"), ("new_tier", "cheapest_adequate_tier"),
                               ("new_gate", "expected_gate")):
                if (row.get(col) or "").strip():
                    changes[field] = row[col].strip()
            rules_cell = (row.get("new_rules") or "").strip()
            if rules_cell:
                changes["expected_rules"] = () if rules_cell.lower() in ("none", "-") else tuple(_rules(rules_cell))
            if not changes:
                errors.append(f"{rid}: decision=change but no new_* value given (use agree to keep the labels)")
                continue
        new[rid] = dataclasses.replace(it, tags=tuple(tags), labeler="owner", review="owner_reviewed", **changes)
        counts[dec] += 1
    missing = sorted(set(by_id) - seen)
    if missing:
        errors.append(f"sheet is missing rows for: {', '.join(missing)}")
    out = [new[i.id] for i in items]
    errors += [f"after applying: {p}" for p in gs.problems(out)]
    if errors:
        return None, counts, errors
    counts["still_draft"] = len(gs.unreviewed(out))
    return out, counts, []


def apply_decisions(items: list[gs.GoldenItem], rows: list[dict]) -> tuple[list[gs.GoldenItem], dict]:
    """As check_decisions, but raises ReviewError (a ValueError) listing every bad row."""
    out, counts, problems = check_decisions(items, rows)
    if problems:
        raise ReviewError(problems)
    return out, counts


def write_jsonl(items: Iterable[gs.GoldenItem], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        for it in items:
            d = dataclasses.asdict(it)
            d["expected_rules"], d["tags"] = list(it.expected_rules), list(it.tags)
            fh.write(json.dumps(d, ensure_ascii=True) + "\r\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write the review CSV")
    e.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("apply", help="apply a filled CSV to a new JSONL (never in place)")
    a.add_argument("--sheet", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    items = gs.load()
    if args.cmd == "export":
        print(f"wrote {export_sheet(items, args.out)} rows to {args.out}")
        return 0
    if args.out.resolve() == gs.DATA_PATH.resolve():
        print("refusing to overwrite the committed golden set; write elsewhere and copy it yourself", file=sys.stderr)
        return 2
    with open(args.sheet, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    out, counts, problems = check_decisions(items, rows)
    if problems:
        print("not applied:\n" + "\n".join(problems), file=sys.stderr)
        return 2
    write_jsonl(out, args.out)
    print(f"wrote {args.out}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
