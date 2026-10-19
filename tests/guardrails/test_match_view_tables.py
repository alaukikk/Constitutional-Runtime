
"""CP-002 RF-4 / N-05: the matching-view character tables are explicit and pinned.

Why: guardrails/match_view.py decides what counts as an invisible character, a space, a hyphen, an
apostrophe or a look-alike letter from EXPLICIT code point tables, not from Unicode categories, so a
Python upgrade cannot silently change what Stage 0/1 match. These tests compare the committed Cf and
Zs tables with the running interpreter's unicodedata and fail with a "review required" message when
they differ. Pinned does not mean endorsed: a drift means a person must look at the new code points.

Version handling: the tables were generated on Unicode PINNED_UNICODE_VERSION. A NEWER interpreter
must classify exactly the same code points (any new Cf/Zs character is a reviewed decision). An OLDER
interpreter (CI runs Python 3.11 = Unicode 14) legitimately lacks characters assigned later, so there
only the "nothing unreviewed appears" direction is checked.
"""
import unicodedata

import pytest

import guardrails.match_view as mv


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def _running_category(cat: str) -> set[int]:
    return {cp for cp in range(0x110000) if unicodedata.category(chr(cp)) == cat}


def _committed(ranges) -> set[int]:
    return {cp for lo, hi in ranges for cp in range(lo, hi + 1)}


def _drift_message(table: str, extra: set[int], missing: set[int]) -> str:
    fmt = lambda s: ", ".join(f"U+{c:04X}" for c in sorted(s)) or "none"
    return (f"UNICODE TABLE DRIFT ({table}): review required. Running unicodedata "
            f"{unicodedata.unidata_version}, tables pinned to {mv.PINNED_UNICODE_VERSION}. "
            f"Not in the committed table: {fmt(extra)}. Committed but not in the running data: "
            f"{fmt(missing)}. Decide whether each code point should be matched as invisible/space, "
            f"update guardrails/match_view.py and PINNED_UNICODE_VERSION, and re-review.")


def _check_drift(table: str, committed: set[int], running: set[int]) -> None:
    unreviewed = running - committed                 # a new character nobody has looked at
    assert not unreviewed, _drift_message(table, unreviewed, set())
    if _version(unicodedata.unidata_version) >= _version(mv.PINNED_UNICODE_VERSION):
        removed = committed - running
        assert not removed, _drift_message(table, set(), removed)


def test_cf_table_matches_the_running_unicode_data():
    committed = _committed(mv.CF_RANGES)
    running = _running_category("Cf")
    # U+180E is Cf on Unicode >= 6.3 and Zs before; it is listed in set I explicitly either way.
    _check_drift("Cf / CF_RANGES", committed - {0x180E} if 0x180E not in running else committed, running)


def test_zs_table_matches_the_running_unicode_data():
    _check_drift("Zs / ZS_RANGES", _committed(mv.ZS_RANGES), _running_category("Zs"))


def test_the_drift_message_names_the_code_points_and_says_review_required():
    msg = _drift_message("demo", {0x2065}, {0x00AD})
    assert "review required" in msg and "U+2065" in msg and "U+00AD" in msg


def test_a_new_format_character_would_fail_the_drift_check():
    with pytest.raises(AssertionError, match="review required"):
        _check_drift("Cf / CF_RANGES", _committed(mv.CF_RANGES), _running_category("Cf") | {0x2065})


# ---- golden content of the pinned tables ----

def test_cf_table_has_170_code_points_on_the_pinned_version():
    assert len(_committed(mv.CF_RANGES)) == 170
    assert mv.PINNED_UNICODE_VERSION == "15.1.0"


def test_set_i_is_cf_plus_the_listed_extras_and_nothing_else():
    extras = {0x034F, 0x115F, 0x1160, 0x2800, 0x3164, 0xFFA0} | set(range(0xFE00, 0xFE10)) \
        | set(range(0xE0100, 0xE01F0))
    assert {ord(c) for c in mv.INVISIBLE} == _committed(mv.CF_RANGES) | extras


@pytest.mark.parametrize("cp", [0x00AD, 0x200B, 0x200C, 0x200D, 0x200E, 0x2060, 0xFEFF, 0xE0041,
                                0xFE0F, 0xE0100, 0x034F, 0x3164, 0x2800, 0x180E])
def test_known_invisible_characters_are_in_set_i(cp):
    assert chr(cp) in mv.INVISIBLE


@pytest.mark.parametrize("ch", ["a", " ", "\t", "\n", "-", "'", "\u00e9", "\U0001F600", "\u0301"])
def test_ordinary_characters_are_not_in_set_i(ch):
    assert ch not in mv.INVISIBLE


def test_whitespace_hyphen_apostrophe_and_line_break_tables_are_exactly_the_approved_ones():
    assert {ord(c) for c in mv.LINE_BREAKS} == {0x0A, 0x0D, 0x0B, 0x0C, 0x85, 0x2028, 0x2029}
    assert {ord(c) for c in mv.ZS} == {0x20, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000}
    assert {ord(c) for c in mv.HYPHEN_LIKES} == {0x2D, 0x5F, *range(0x2010, 0x2016), 0x2212, 0xFE58, 0xFE63}
    assert {ord(c) for c in mv.APOSTROPHES} == {0x27, 0x60, 0xB4, 0x2BC, 0x2018, 0x2019, 0x2032}


def test_confusable_table_has_25_single_letter_entries_and_no_greek_tau():
    assert len(mv.CONFUSABLES) == 25
    for src, dst in mv.CONFUSABLES.items():
        assert len(src) == 1 and src == src.lower() and src.isalpha()
        assert len(dst) == 1 and dst in "abcdefghijklmnopqrstuvwxyz"
        assert src != dst
    assert "\u03c4" not in mv.CONFUSABLES                       # D-7: dropped
    assert sum(1 for s in mv.CONFUSABLES if "\u0400" <= s <= "\u052f") == 15      # Cyrillic
    assert sum(1 for s in mv.CONFUSABLES if "\u0370" <= s <= "\u03ff") == 9       # Greek


def test_confusable_sources_are_stable_under_nfkc_so_they_reach_the_table_unchanged():
    for src in mv.CONFUSABLES:
        assert unicodedata.normalize("NFKC", src) == src


def test_the_tables_do_not_overlap_in_ways_that_would_make_a_rule_ambiguous():
    groups = {"invisible": mv.INVISIBLE, "zs": mv.ZS, "line_breaks": mv.LINE_BREAKS,
              "hyphens": mv.HYPHEN_LIKES, "apostrophes": mv.APOSTROPHES,
              "confusables": frozenset(mv.CONFUSABLES)}
    names = list(groups)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not (groups[a] & groups[b]), f"{a} and {b} overlap: {groups[a] & groups[b]!r}"


# ---- the only category-based logic left: emoji context (So / Sk), pinned here ----

@pytest.mark.parametrize("ch, cat", [
    ("\U0001F600", "So"), ("\U0001F468", "So"), ("\U0001F3F4", "So"), ("\u2764", "So"),
    ("\U0001F525", "So"), ("\u2640", "So"), ("\U0001F1EE", "So"),
    ("\U0001F3FD", "Sk"),                                            # skin-tone modifier
    ("\u2800", "So"),                                                # Braille blank: So AND invisible
    ("\u203c", "Po"), ("\u2139", "Ll"), ("\u2194", "Sm"), ("\u3030", "Pd"), ("\u303d", "Po"),
])
def test_emoji_context_categories_are_pinned(ch, cat):
    assert unicodedata.category(ch) == cat, (
        f"U+{ord(ch):04X} changed category: review required for the emoji-context rules in match_view.py")


def test_emoji_symbol_test_never_treats_an_invisible_character_as_an_emoji():
    assert not mv._is_emoji_symbol("\u2800")
    assert all(not mv._is_emoji_symbol(c) for c in mv.INVISIBLE)
