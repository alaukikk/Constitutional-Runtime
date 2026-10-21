
import csv

import pytest

from evaluation import golden_set as gs
from evaluation import review as rv

ITEMS = gs.load()


def rows_for(decisions=None, **per_id):
    """Blank sheet rows; per_id maps an id to a dict of cells to set."""
    out = [{"id": i.id, "decision": ""} for i in ITEMS]
    for r in out:
        r.update(per_id.get(r["id"], {}))
    return out


def test_export_round_trips_and_hides_system_results(tmp_path):
    p = tmp_path / "sheet.csv"
    assert rv.export_sheet(ITEMS, p) == len(ITEMS)
    with open(p, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["id"] for r in rows] == [i.id for i in ITEMS]
    assert set(rv.COLUMNS) == set(rows[0])
    forbidden = ("actual", "classified", "attempt", "fired", "stage0")
    assert not any(f in c for c in rows[0] for f in forbidden)          # no system output on the sheet


def test_invisible_characters_are_shown_as_escapes(tmp_path):
    zw = next(i for i in ITEMS if "\u200b" in i.text)
    assert "\\u200b" in rv.display(zw.text) and "\u200b" not in rv.display(zw.text)
    assert rv.display("a\nb") == "a\\nb" and rv.display("\U0001F600") == "\\U0001f600"


def test_blank_sheet_changes_nothing():
    out, counts = rv.apply_decisions(ITEMS, rows_for())
    assert out == ITEMS and counts["skip"] == len(ITEMS)


def test_agree_adopts_label_and_keeps_text():
    plain = next(i for i in ITEMS if "contested" not in i.tags)
    out, counts = rv.apply_decisions(ITEMS, rows_for(**{plain.id: {"decision": "agree"}}))
    got = next(i for i in out if i.id == plain.id)
    assert got.labeler == "owner" and got.review == "owner_reviewed" and got.text == plain.text
    assert got.true_type == plain.true_type and counts["agree"] == 1


def test_contested_needs_explicit_settlement():
    c = next(i for i in ITEMS if "contested" in i.tags)
    with pytest.raises(ValueError, match="contested_resolved=yes"):
        rv.apply_decisions(ITEMS, rows_for(**{c.id: {"decision": "agree"}}))
    out, _ = rv.apply_decisions(ITEMS, rows_for(**{c.id: {"decision": "agree", "contested_resolved": "yes"}}))
    assert "contested" not in next(i for i in out if i.id == c.id).tags


def test_change_applies_new_values_and_validates():
    it = next(i for i in ITEMS if i.id == "G-060")                 # policy gap, require_human with no rule
    ok = {"decision": "change", "contested_resolved": "yes", "new_gate": "allow"}
    out, _ = rv.apply_decisions(ITEMS, rows_for(**{it.id: ok}))
    settled = next(i for i in out if i.id == it.id)
    assert settled.expected_gate == "allow"
    assert "policy_gap" not in settled.tags and "contested" not in settled.tags   # no longer a recall gap
    ok2 = {"decision": "change", "contested_resolved": "yes", "new_rules": "HAC-001"}
    out2, _ = rv.apply_decisions(ITEMS, rows_for(**{it.id: ok2}))
    assert next(i for i in out2 if i.id == it.id).expected_rules == ("HAC-001",)


def test_change_that_breaks_integrity_is_refused():
    with pytest.raises(ValueError, match="after applying"):
        rv.apply_decisions(ITEMS, rows_for(**{"G-001": {"decision": "change", "new_gate": "block"}}))


@pytest.mark.parametrize("cells,needle", [
    ({"decision": "maybe"}, "must be agree, change or blank"),
    ({"decision": "change"}, "but no new_"),
])
def test_bad_decisions_are_errors_not_guesses(cells, needle):
    with pytest.raises(ValueError, match=needle):
        rv.apply_decisions(ITEMS, rows_for(**{"G-001": cells}))


def test_missing_unknown_and_duplicate_rows_are_reported():
    rows = rows_for()[1:] + [{"id": "G-999", "decision": ""}, {"id": "G-002", "decision": ""}]
    with pytest.raises(ValueError) as e:
        rv.apply_decisions(ITEMS, rows)
    msg = str(e.value)
    assert "missing rows for: G-001" in msg and "G-999" in msg and "appears twice" in msg


def test_cli_refuses_to_overwrite_the_committed_set(tmp_path):
    sheet = tmp_path / "s.csv"
    rv.export_sheet(ITEMS, sheet)
    assert rv.main(["apply", "--sheet", str(sheet), "--out", str(gs.DATA_PATH)]) == 2


def test_cli_end_to_end(tmp_path):
    sheet, out = tmp_path / "s.csv", tmp_path / "reviewed.jsonl"
    rv.main(["export", "--out", str(sheet)])
    with open(sheet, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["decision"] = "agree"
    with open(sheet, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=rv.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    assert rv.main(["apply", "--sheet", str(sheet), "--out", str(out)]) == 0
    reviewed = gs.load(out)
    assert reviewed[0].review == "owner_reviewed" and reviewed[1].review == "draft"
    assert [i.text for i in reviewed] == [i.text for i in ITEMS]


def test_cli_reports_problems_and_writes_nothing(tmp_path, capsys):
    sheet, out = tmp_path / "s.csv", tmp_path / "o.jsonl"
    rv.main(["export", "--out", str(sheet)])
    with open(sheet, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["decision"] = "maybe"
    with open(sheet, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=rv.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    assert rv.main(["apply", "--sheet", str(sheet), "--out", str(out)]) == 2
    assert "must be agree, change or blank" in capsys.readouterr().err
    assert not out.exists()
