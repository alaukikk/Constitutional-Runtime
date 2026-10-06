
"""OI-067 governance: integrity log, CODEOWNERS copies.

The synthetic-root tests exercise the log mechanics in isolation. The two
`test_repo_*` tests run against the REAL repository: they are the "changing a
constitutional file without a governance record fails" guarantee, and they
fail until the owner has recorded a baseline (see the message they print).
"""
import json
from pathlib import Path

import pytest

from policy.governance import change_log as cl
from policy.governance.change_log import (
    GOVERNED_FILES, append_entry, check_integrity, current_hashes, hash_governed_file, read_log,
)

# Same root change_log.py uses, so this test works wherever it sits under tests/.
REPO_ROOT = cl._PROJECT_ROOT
CANONICAL = REPO_ROOT / "policy" / "governance" / "CODEOWNERS"
GITHUB_COPY = REPO_ROOT / ".github" / "CODEOWNERS"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config").mkdir()
    # write_bytes, not write_text: write_text turns "\n" into CRLF on Windows, which would
    # make these fixtures platform-dependent.
    (tmp_path / "config" / "constitution.yaml").write_bytes(b"rules:\n  - rule_id: A\n")
    (tmp_path / "config" / "failure_modes.yaml").write_bytes(b"default:\n  fail_closed: true\n")
    return tmp_path


@pytest.fixture
def log(tmp_path):
    return tmp_path / "change_log.jsonl"


def record(root, log, decision="ACCEPT", who="owner", component="config/constitution.yaml",
           description="reason", **kw):
    return append_entry(component, decision, who, description, log_path=log, root=root, **kw)


def edit(root, rel="config/constitution.yaml", text="rules:\n  - rule_id: B\n"):
    (root / rel).write_bytes(text.encode("utf-8"))


def report(root, log):
    return check_integrity(log, root)


# ---- the core guarantee: a change without a new record is detected ----

def test_baseline_then_clean(root, log):
    record(root, log)
    r = report(root, log)
    assert r.records_match and r.problems == () and r.entries_checked == 1


@pytest.mark.parametrize("rel", GOVERNED_FILES)
def test_changing_either_governed_file_without_a_record_fails(root, log, rel):
    record(root, log)
    edit(root, rel, "changed: true\n")
    r = report(root, log)
    assert not r.records_match
    assert any(rel in p and "changed since the latest governance record" in p for p in r.problems)
    assert any("change_log append" in p for p in r.problems)    # tells the owner what to do


def test_recording_the_change_restores_a_match(root, log):
    record(root, log)
    edit(root)
    assert not report(root, log).records_match
    append_entry("config/constitution.yaml", "ACCEPT", "owner", "added rule B", log_path=log, root=root)
    assert report(root, log).records_match


def test_whitespace_only_change_is_still_a_change(root, log):
    record(root, log)
    edit(root, text="rules:\n  - rule_id: A\n\n")
    assert not report(root, log).records_match


def test_missing_log_or_empty_log_fails(root, log):
    assert not report(root, log).records_match
    log.write_text("", encoding="utf-8")
    r = report(root, log)
    assert not r.records_match and any("empty" in p for p in r.problems)


def test_missing_governed_file_fails(root, log):
    record(root, log)
    (root / "config" / "failure_modes.yaml").unlink()
    r = report(root, log)
    assert not r.records_match and any("failure_modes.yaml is missing" in p for p in r.problems)


# ---- hashing ----

def test_line_endings_do_not_change_the_hash(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b"x: 1\ny: 2\n")
    b.write_bytes(b"x: 1\r\ny: 2\r\n")
    c.write_bytes(b"x: 1\ry: 2\r")
    assert hash_governed_file(a) == hash_governed_file(b) == hash_governed_file(c)


def test_crlf_checkout_still_matches_a_lf_record(root, log):
    record(root, log)
    for rel in GOVERNED_FILES:
        p = root / rel
        lf = p.read_bytes().replace(b"\r\n", b"\n")
        p.write_bytes(lf.replace(b"\n", b"\r\n"))
    assert report(root, log).records_match


def test_current_hashes_reports_missing_as_none(root):
    (root / "config" / "constitution.yaml").unlink()
    h = current_hashes(root)
    assert h["config/constitution.yaml"] is None and h["config/failure_modes.yaml"]


# ---- record rules ----

def test_first_record_must_be_accept(root, log):
    for d in ("REJECT", "DEFER"):
        with pytest.raises(ValueError):
            record(root, log, decision=d)
    assert not log.exists()


def test_first_record_not_accept_is_flagged_if_written_by_hand(root, log):
    h = current_hashes(root)
    log.write_text(json.dumps({"entry": 1, "date": "2026-10-06", "component": "x", "decision": "DEFER",
                               "decided_by": "o", "description": "", "change_proposal": None,
                               "hashes": h}) + "\n", encoding="utf-8")
    r = report(root, log)
    assert not r.records_match and any("first record must be an ACCEPT" in p for p in r.problems)


def test_reject_or_defer_with_unchanged_files_is_fine(root, log):
    record(root, log)
    record(root, log, decision="REJECT", description="proposed change declined")
    record(root, log, decision="DEFER")
    assert report(root, log).records_match


def test_reject_cannot_accompany_changed_files(root, log):
    record(root, log)
    edit(root)
    with pytest.raises(ValueError, match="REJECT"):
        record(root, log, decision="REJECT")
    with pytest.raises(ValueError, match="DEFER"):
        record(root, log, decision="DEFER")


def test_hand_written_reject_with_changed_hashes_is_flagged(root, log):
    record(root, log)
    edit(root)
    bad = {"entry": 2, "date": "2026-10-06", "component": "x", "decision": "REJECT", "decided_by": "o",
           "description": "", "change_proposal": None, "hashes": current_hashes(root)}
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(bad) + "\n")
    r = report(root, log)
    assert not r.records_match and any("REJECT record must carry the same hashes" in p for p in r.problems)


def test_deleted_record_is_detected_by_numbering(root, log):
    record(root, log)
    edit(root, text="a: 1\n")
    record(root, log)
    edit(root, text="a: 2\n")
    record(root, log)
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")   # drop the middle record
    r = report(root, log)
    assert not r.records_match and any("'entry' must be 2" in p for p in r.problems)


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e.update(decision="APPROVE"), "'decision' must be one of"),
    (lambda e: e.update(decided_by="  "), "'decided_by' must be a non-empty string"),
    (lambda e: e.update(component=""), "'component' must be a non-empty string"),
    (lambda e: e.update(date="06/10/2026"), "'date' must be an ISO date"),
    (lambda e: e["hashes"].pop("config/failure_modes.yaml"), "'hashes' must have exactly the keys"),
    (lambda e: e["hashes"].update({"config/constitution.yaml": "abc"}), "64-character"),
])
def test_malformed_records_fail(root, log, mutate, needle):
    record(root, log)
    e = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    mutate(e)
    log.write_text(json.dumps(e) + "\n", encoding="utf-8")
    r = report(root, log)
    assert not r.records_match and any(needle in p for p in r.problems)


def test_non_json_line_fails(root, log):
    record(root, log)
    with open(log, "a", encoding="utf-8") as f:
        f.write("this is not json\n")
    r = report(root, log)
    assert not r.records_match and any("not valid JSON" in p for p in r.problems)


def test_malformed_log_blocks_appending(root, log):
    log.write_text("garbage\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        record(root, log)


@pytest.mark.parametrize("kw", [
    dict(decision="APPROVE"), dict(who=""), dict(who="   "), dict(component=""), dict(date="yesterday"),
])
def test_append_rejects_invalid_input(root, log, kw):
    with pytest.raises(ValueError):
        record(root, log, **kw)
    assert not log.exists()


def test_append_refuses_when_a_governed_file_is_missing(root, log):
    (root / "config" / "constitution.yaml").unlink()
    with pytest.raises(ValueError, match="missing"):
        record(root, log)


def test_append_adds_a_missing_trailing_newline(root, log):
    record(root, log)
    log.write_text(log.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")   # no final newline
    edit(root)
    record(root, log)
    entries, problems = read_log(log)
    assert problems == [] and [e.entry for e in entries] == [1, 2]


def test_record_stores_what_it_is_told(root, log):
    e = record(root, log, who="Some Person", date="2026-10-06", change_proposal="CP-001")
    assert (e.entry, e.decided_by, e.date, e.change_proposal) == (1, "Some Person", "2026-10-06", "CP-001")
    assert set(e.hashes) == set(GOVERNED_FILES)


# ---- boundary: a record is not approval ----

def test_report_makes_no_approval_claim(root, log):
    record(root, log)
    r = report(root, log)
    assert not hasattr(r, "approved") and not hasattr(r, "reviewed")


def test_a_matching_record_by_anyone_passes_because_it_proves_a_record_not_approval(root, log):
    """Documents the limit on purpose: the check cannot know whether 'nobody' had
    authority. Authority is enforced by code-owner review on `main`, not here."""
    record(root, log, who="nobody-in-particular")
    edit(root)
    append_entry("config/constitution.yaml", "ACCEPT", "nobody-in-particular", "", log_path=log, root=root)
    assert report(root, log).records_match


def test_cli_check_message_does_not_claim_approval(root, log, monkeypatch, capsys):
    record(root, log)
    monkeypatch.setattr(cl, "LOG_PATH", log)
    monkeypatch.setattr(cl, "_PROJECT_ROOT", root)
    monkeypatch.setattr(cl, "check_integrity", lambda: check_integrity(log, root))
    assert cl._cli(["check"]) == 0
    assert "does not by itself show that any change was reviewed or approved" in capsys.readouterr().out


def test_cli_check_fails_with_exit_code_1_on_drift(root, log, monkeypatch, capsys):
    record(root, log)
    edit(root)
    monkeypatch.setattr(cl, "check_integrity", lambda: check_integrity(log, root))
    assert cl._cli(["check"]) == 1
    assert "PROBLEM" in capsys.readouterr().err


# ---- the real repository ----

def test_repo_governance_log_matches_governed_files():
    r = check_integrity()
    assert r.records_match, (
        "governed constitutional files and the governance log disagree (this does not mean "
        "anything was approved or rejected, only that a record is missing or malformed):\n  - "
        + "\n  - ".join(r.problems))


# ---- CODEOWNERS ----

def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def _rules(path):
    out = []
    for line in _read_lines(path):
        s = line.strip()
        if s and not s.startswith("#"):
            pattern, *owners = s.split()
            out.append((pattern, owners))
    return out


def _covers(pattern, rel):
    p = pattern.lstrip("/")
    return rel == p or (pattern.endswith("/") and rel.startswith(p))


def test_both_codeowners_copies_exist():
    assert CANONICAL.is_file(), "policy/governance/CODEOWNERS (canonical copy) is missing"
    assert GITHUB_COPY.is_file(), ".github/CODEOWNERS (the copy GitHub reads) is missing"


def test_codeowners_copies_are_identical_ignoring_line_endings():
    assert _read_lines(CANONICAL) == _read_lines(GITHUB_COPY), (
        "policy/governance/CODEOWNERS and .github/CODEOWNERS have drifted; edit both together")


@pytest.mark.parametrize("path", [CANONICAL, GITHUB_COPY], ids=["canonical", "github"])
def test_codeowners_rules_are_well_formed(path):
    rules = _rules(path)
    assert rules, "CODEOWNERS has no rules"
    for pattern, owners in rules:
        assert owners, f"rule {pattern} has no owner"
        assert all(o.startswith("@") and len(o) > 1 for o in owners), f"bad owner on {pattern}: {owners}"


@pytest.mark.parametrize("rel", GOVERNED_FILES)
def test_every_governed_file_is_covered_by_a_code_owner_rule(rel):
    assert any(_covers(p, rel) for p, _ in _rules(GITHUB_COPY)), f"{rel} has no code-owner rule"


@pytest.mark.parametrize("rel", ["policy/governance/change_log.py", "policy/governance/change_log.jsonl",
                                 "docs/ARCHITECTURE.md", "docs/CONSTITUTION.md", ".github/CODEOWNERS"])
def test_governance_machinery_and_frozen_docs_are_covered(rel):
    assert any(_covers(p, rel) for p, _ in _rules(GITHUB_COPY)), f"{rel} has no code-owner rule"


def test_codeowners_states_that_it_does_not_enforce_by_itself():
    text = CANONICAL.read_text(encoding="utf-8").lower()
    assert "does not itself enforce" in text or "does not enforce" in text
    assert "branch protection" in text and "code owners" in text and "bypass" in text
