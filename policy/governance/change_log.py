
"""
policy/governance/change_log.py -- machine-readable governance/integrity log (OI-067).

WHAT THIS IS. An append-only JSON Lines file (policy/governance/change_log.jsonl)
in which the project owner records a decision about the governed constitutional
files, together with a SHA-256 hash of each file as it stands at that moment.
check_integrity() compares the newest record with the files on disk, so editing
either governed file WITHOUT adding a new record is detected (no AI involved).

WHAT THIS IS NOT (important boundary). A matching log proves only that a record
EXISTS for the current content of the files. It does NOT prove the change was
reviewed, that `decided_by` is who they claim to be, or that the decision was
made through the Change Proposal process. Nothing here infers approval from the
presence of an entry: IntegrityReport deliberately has no "approved" field.
Review itself is enforced (if at all) by GitHub code-owner review on `main`
(CODEOWNERS plus branch protection, a repository setting this code cannot
configure), and the log is a plain file whose history is protected only by git.

Governed files [JUDGMENT]: config/constitution.yaml and config/failure_modes.yaml
-- the runtime constitution and its failure semantics. ARCHITECTURE.md is frozen
under CONSTITUTION.md's Change Proposal process and is covered by CODEOWNERS, not
by this hash log.

Hashing [JUDGMENT]: line endings are normalised (CRLF/CR -> LF) before hashing,
because this repository has mixed line endings (OI-038) and a Windows checkout
with autocrlf would otherwise produce a different hash for identical content.
Any other byte difference, including whitespace and comments, changes the hash.

Record rules enforced by check_integrity():
  * entries are numbered 1..n with no gaps (a deleted record is detected);
  * the first record must be ACCEPT (a baseline); later ones may be ACCEPT,
    REJECT or DEFER;
  * a REJECT/DEFER record must carry the SAME hashes as the record before it,
    because declining a change means the files did not change;
  * the newest record's hashes must equal the files on disk.

Typical use (from the repository root):
    python -m policy.governance.change_log append --component config/constitution.yaml \
        --decision ACCEPT --decided-by <name> --description "why"
    python -m policy.governance.change_log check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = Path(__file__).resolve().with_name("change_log.jsonl")

GOVERNED_FILES: tuple[str, ...] = ("config/constitution.yaml", "config/failure_modes.yaml")
DECISIONS: tuple[str, ...] = ("ACCEPT", "REJECT", "DEFER")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REMEDY = ("python -m policy.governance.change_log append --component <file> "
           "--decision ACCEPT --decided-by <name> --description \"<why>\"")


# --------------------------------------------------------------------------- hashing

def hash_governed_file(path: Path) -> str:
    """SHA-256 of the file content with line endings normalised to LF."""
    data = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def current_hashes(root: Path = _PROJECT_ROOT) -> dict[str, Optional[str]]:
    """Hash of each governed file under `root`; None for a file that is missing."""
    out: dict[str, Optional[str]] = {}
    for rel in GOVERNED_FILES:
        p = Path(root) / rel
        out[rel] = hash_governed_file(p) if p.is_file() else None
    return out


# --------------------------------------------------------------------------- records

@dataclass(frozen=True)
class LogEntry:
    entry: int
    date: str
    component: str
    decision: str
    decided_by: str
    description: str
    change_proposal: Optional[str]
    hashes: dict


@dataclass(frozen=True)
class IntegrityReport:
    """Result of comparing the log with the governed files.

    `records_match` means ONLY "the log is well-formed and its newest record
    matches the files on disk". It is not a statement that anything was approved.
    """
    records_match: bool
    problems: tuple[str, ...]
    entries_checked: int


def _parse_entry(raw: object, index: int) -> tuple[Optional[LogEntry], list[str]]:
    where = f"entry {index}"
    if not isinstance(raw, dict):
        return None, [f"{where}: not a JSON object"]
    problems: list[str] = []

    if raw.get("entry") != index or isinstance(raw.get("entry"), bool):
        problems.append(f"{where}: 'entry' must be {index} (entries are numbered 1..n without gaps; "
                        f"a missing or renumbered record is treated as tampering)")
    try:
        _date.fromisoformat(str(raw.get("date")))
    except ValueError:
        problems.append(f"{where}: 'date' must be an ISO date (YYYY-MM-DD), got {raw.get('date')!r}")
    for field in ("component", "decided_by"):
        v = raw.get(field)
        if not isinstance(v, str) or not v.strip():
            problems.append(f"{where}: '{field}' must be a non-empty string")
    if raw.get("decision") not in DECISIONS:
        problems.append(f"{where}: 'decision' must be one of {DECISIONS}, got {raw.get('decision')!r}")
    desc = raw.get("description", "")
    if not isinstance(desc, str):
        problems.append(f"{where}: 'description' must be a string")
    cp = raw.get("change_proposal")
    if cp is not None and not isinstance(cp, str):
        problems.append(f"{where}: 'change_proposal' must be a string or null")

    hashes = raw.get("hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(GOVERNED_FILES):
        problems.append(f"{where}: 'hashes' must have exactly the keys {list(GOVERNED_FILES)}")
    else:
        for k, v in hashes.items():
            if not isinstance(v, str) or not _HEX64.match(v):
                problems.append(f"{where}: hash for {k} is not a 64-character lowercase hex SHA-256")

    if problems:
        return None, problems
    return LogEntry(index, raw["date"], raw["component"], raw["decision"], raw["decided_by"],
                    desc, cp, dict(hashes)), []


def read_log(log_path: Path = LOG_PATH) -> tuple[list[LogEntry], list[str]]:
    """Parse the log. Never raises on bad content: returns (entries, problems)."""
    p = Path(log_path)
    if not p.is_file():
        return [], [f"governance log {p.name} does not exist"]
    entries: list[LogEntry] = []
    problems: list[str] = []
    index = 0
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        index += 1
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"line {lineno}: not valid JSON ({exc.msg})")
            continue
        entry, errs = _parse_entry(raw, index)
        problems.extend(errs)
        if entry is not None:
            entries.append(entry)
    return entries, problems


# --------------------------------------------------------------------------- integrity

def check_integrity(log_path: Path = LOG_PATH, root: Path = _PROJECT_ROOT) -> IntegrityReport:
    """Detect governed-file changes that have no matching governance record."""
    entries, structural = read_log(log_path)
    problems = list(structural)

    if not entries and not problems:
        problems.append("governance log is empty: the governed files have no record")

    prev: Optional[LogEntry] = None
    for e in entries:
        if prev is None and e.decision != "ACCEPT":
            problems.append(f"entry {e.entry}: the first record must be an ACCEPT baseline, got {e.decision}")
        if prev is not None and e.decision in ("REJECT", "DEFER") and e.hashes != prev.hashes:
            problems.append(f"entry {e.entry}: a {e.decision} record must carry the same hashes as entry "
                            f"{prev.entry} (declining a change means the files did not change)")
        prev = e

    current = current_hashes(root)
    for rel, h in current.items():
        if h is None:
            problems.append(f"governed file {rel} is missing")

    if entries and not structural:
        # Only compare with the disk when the log itself parsed cleanly; otherwise
        # the structural problems above are the actionable message.
        latest = entries[-1]
        for rel in GOVERNED_FILES:
            have = current[rel]
            if have is not None and have != latest.hashes[rel]:
                problems.append(
                    f"{rel} changed since the latest governance record (entry {latest.entry}); "
                    f"recorded {latest.hashes[rel][:12]}..., found {have[:12]}.... "
                    f"Record a decision for this change: {_REMEDY}")

    return IntegrityReport(not problems, tuple(problems), len(entries))


# --------------------------------------------------------------------------- appending

def append_entry(
    component: str,
    decision: str,
    decided_by: str,
    description: str = "",
    *,
    change_proposal: Optional[str] = None,
    date: Optional[str] = None,
    log_path: Path = LOG_PATH,
    root: Path = _PROJECT_ROOT,
) -> LogEntry:
    """Append one record for the CURRENT content of the governed files.

    Recording a decision is a human act: this function stores what it is told and
    cannot verify that the decision was actually made or by whom. Raises
    ValueError on invalid input or an unusable existing log (audit-write problems
    fail loud).
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    for name, value in (("component", component), ("decided_by", decided_by)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if not isinstance(description, str):
        raise ValueError("description must be a string")
    when = date or datetime.now(timezone.utc).date().isoformat()
    try:
        _date.fromisoformat(when)
    except ValueError:
        raise ValueError(f"date must be an ISO date (YYYY-MM-DD), got {when!r}") from None

    path = Path(log_path)
    entries, problems = read_log(path) if path.is_file() else ([], [])
    if problems:
        raise ValueError("existing governance log is malformed, fix it before appending: "
                         + "; ".join(problems))

    hashes = current_hashes(root)
    missing = [rel for rel, h in hashes.items() if h is None]
    if missing:
        raise ValueError(f"cannot record: governed file(s) missing: {missing}")

    if not entries and decision != "ACCEPT":
        raise ValueError("the first governance record must be an ACCEPT baseline")
    if entries and decision in ("REJECT", "DEFER") and hashes != entries[-1].hashes:
        raise ValueError(f"a {decision} record cannot accompany changed governed files; "
                         f"revert the change, or record ACCEPT if it was accepted")

    entry = LogEntry(len(entries) + 1, when, component.strip(), decision, decided_by.strip(),
                     description, change_proposal, hashes)
    line = json.dumps({
        "entry": entry.entry, "date": entry.date, "component": entry.component,
        "decision": entry.decision, "decided_by": entry.decided_by,
        "description": entry.description, "change_proposal": entry.change_proposal,
        "hashes": entry.hashes,
    }, ensure_ascii=False)

    existing = path.read_bytes() if path.is_file() else b""
    prefix = "" if not existing or existing.endswith(b"\n") else "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(prefix + line + "\n")
    return entry


# --------------------------------------------------------------------------- CLI

def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m policy.governance.change_log",
                                     description="Governance integrity log for the constitutional files.")
    sub = parser.add_subparsers(dest="command", required=True)

    ap = sub.add_parser("append", help="record a decision for the current content of the governed files")
    ap.add_argument("--component", required=True)
    ap.add_argument("--decision", required=True, choices=DECISIONS)
    ap.add_argument("--decided-by", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--change-proposal", default=None)
    ap.add_argument("--date", default=None, help="ISO date; defaults to today (UTC)")

    sub.add_parser("check", help="verify the log matches the governed files")

    args = parser.parse_args(argv)
    if args.command == "append":
        try:
            e = append_entry(args.component, args.decision, args.decided_by, args.description,
                             change_proposal=args.change_proposal, date=args.date)
        except ValueError as exc:
            print(f"not recorded: {exc}", file=sys.stderr)
            return 2
        print(f"recorded entry {e.entry}: {e.decision} {e.component} by {e.decided_by} on {e.date}")
        return 0

    report = check_integrity()
    if report.records_match:
        print(f"governance log matches the governed files ({report.entries_checked} record(s)); "
              f"this does not by itself show that any change was reviewed or approved")
        return 0
    for p in report.problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
