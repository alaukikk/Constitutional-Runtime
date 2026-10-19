
"""CP-002 N-03: the `repeated_zero_width` signal and the emoji exemption (RF-1, RF-2, D-2).

SUSPICIOUS at 2 or more invisible characters (guardrails/match_view.py::count_invisible) that are not
part of a WELL-FORMED emoji sequence. The threshold is a provisional [JUDGMENT] value. The exemption
must be narrow: adjacency to an emoji is NOT enough.
"""
import pytest

from guardrails.injection_screen import ScreenVerdict, screen_request
from guardrails.match_view import count_invisible

ZWSP, ZWNJ, ZWJ, BOM, SHY = "\u200b", "\u200c", "\u200d", "\ufeff", "\u00ad"
VS16, VS15, VS1 = "\ufe0f", "\ufe0e", "\ufe00"
SMILE, MAN, WOMAN, GIRL, BOY = "\U0001F600", "\U0001F468", "\U0001F469", "\U0001F467", "\U0001F466"
SKIN = "\U0001F3FD"
HEART, FIRE = "\u2764", "\U0001F525"
FLAG_ENGLAND = "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in "gbeng") + "\U000E007F"
FLAG_SCOTLAND = "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in "gbsct") + "\U000E007F"
FLAG_WALES = "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in "gbwls") + "\U000E007F"


def verdict(text):
    return screen_request(text).verdict


# ---- the threshold ----

@pytest.mark.parametrize("n, expected", [(0, ScreenVerdict.CLEAN), (1, ScreenVerdict.CLEAN),
                                         (2, ScreenVerdict.SUSPICIOUS), (3, ScreenVerdict.SUSPICIOUS)])
def test_threshold_is_two_next_to_ordinary_text(n, expected):
    assert verdict("hello" + ZWSP * n + "world") == expected


def test_a_single_leading_bom_stays_clean():
    assert verdict(BOM + "Tell me about octopuses") == ScreenVerdict.CLEAN


def test_two_zero_width_characters_in_different_words_are_suspicious():
    r = screen_request(f"Tell{ZWSP} me about{ZWSP} octopuses")
    assert r.verdict == ScreenVerdict.SUSPICIOUS and r.matched_patterns == ["repeated_zero_width"]


@pytest.mark.parametrize("ch", [ZWSP, ZWNJ, BOM, SHY, "\u200e", "\u202e", "\u2060", "\u034f", "\u3164", "\u2800", "\ufe00",
                                "\U000E0101"])
def test_each_kind_of_invisible_character_counts(ch):
    assert count_invisible(f"a{ch}b{ch}c") == 2


def test_forty_variation_selectors_are_suspicious():
    assert verdict("hello " + VS1 * 40) == ScreenVerdict.SUSPICIOUS
    assert verdict("hello " + "".join(chr(0xE0100 + i) for i in range(40))) == ScreenVerdict.SUSPICIOUS


def test_the_signal_counts_the_RAW_text_so_it_is_not_defeated_by_normalization_stripping():
    r = screen_request("a" + ZWSP * 4 + "b")
    assert r.normalized_text == "ab" and r.verdict == ScreenVerdict.SUSPICIOUS


# ---- legitimate emoji stay clean (RF-1 / RF-2) ----

@pytest.mark.parametrize("name, text", [
    ("family ZWJ sequence", f"{MAN}{ZWJ}{WOMAN}{ZWJ}{GIRL}{ZWJ}{BOY}"),
    ("three-person family", f"{MAN}{ZWJ}{WOMAN}{ZWJ}{GIRL}"),
    ("heart with VS16", f"I {HEART}{VS16} this"),
    ("skin tone", f"thanks {SMILE}{SKIN}"),
    ("person with skin tone and ZWJ", f"{WOMAN}{SKIN}{ZWJ}\U0001F4BB"),
    ("heart on fire (VS16 then ZWJ)", f"{HEART}{VS16}{ZWJ}{FIRE}"),
    ("keycap", f"press 1{VS16}\u20e3 or #{VS16}\u20e3"),
    ("regional indicator flag", "\U0001F1EE\U0001F1F3"),
    ("England flag", f"come to {FLAG_ENGLAND}"),
    ("Scotland flag", FLAG_SCOTLAND),
    ("Wales flag", FLAG_WALES),
    ("three flags", f"{FLAG_ENGLAND}{FLAG_SCOTLAND}{FLAG_WALES}"),
    ("text-presentation selector after an emoji", f"{HEART}{VS15}"),
    ("many separate emoji sequences", (f"{HEART}{VS16} " * 10).strip()),
])
def test_well_formed_emoji_sequences_are_not_counted(name, text):
    assert count_invisible(text) == 0, name
    assert verdict(text) == ScreenVerdict.CLEAN


# ---- the exemption must be narrow: adjacency to an emoji is not enough (RF-1) ----

def test_interleaved_emoji_and_zero_width_characters_are_suspicious():
    text = (SMILE + ZWSP) * 6 + SMILE
    assert count_invisible(text) == 6 and verdict(text) == ScreenVerdict.SUSPICIOUS


@pytest.mark.parametrize("name, text, expected", [
    ("ZWNJ between emoji", f"{SMILE}{ZWNJ}{SMILE}", 1),
    ("ZWSP between emoji", f"{SMILE}{ZWSP}{SMILE}", 1),
    ("BOM next to an emoji", f"{SMILE}{BOM}", 1),
    ("soft hyphen next to an emoji", f"{SMILE}{SHY}", 1),
    ("ZWJ next to a letter on the left", f"a{ZWJ}{SMILE}", 1),
    ("ZWJ next to a letter on the right", f"{SMILE}{ZWJ}a", 1),
    ("ZWJ with nothing before", f"{ZWJ}{SMILE}", 1),
    ("ZWJ with nothing after", f"{SMILE}{ZWJ}", 1),
    ("selector after a letter", f"a{VS16}", 1),
    ("selector after a space", f" {VS16}", 1),
    ("a second selector after a base", f"{HEART}{VS16}{VS16}", 1),
    ("forty selectors after one emoji", f"{SMILE}" + VS1 * 40, 40),
    ("VS16 run after an emoji", f"{HEART}" + VS16 * 5, 4),
    ("stray tag characters", "a\U000E0067\U000E0062b", 2),
    ("tag sequence without the flag base", "\U000E0067\U000E0062\U000E0065\U000E007F", 4),
    ("flag base without the cancel tag", "\U0001F3F4\U000E0067\U000E0062\U000E0065", 3),
    ("flag with too few tags", "\U0001F3F4\U000E0067\U000E007F", 2),
    ("flag with a non-body tag", "\U0001F3F4\U000E0020\U000E0067\U000E007F", 3),
    ("flag with far too many tags", "\U0001F3F4" + "\U000E0067" * 30 + "\U000E007F", 31),
])
def test_invisible_characters_near_emoji_are_counted_unless_the_sequence_is_well_formed(name, text, expected):
    assert count_invisible(text) == expected, name


def test_a_zwj_next_to_an_emoji_but_a_letter_on_the_other_side_is_counted():
    assert count_invisible(f"{SMILE}{ZWJ}x{ZWJ}{SMILE}") == 2


def test_more_than_three_joiners_in_one_sequence_are_counted():
    chain = ZWJ.join([MAN, WOMAN, GIRL, BOY, MAN, WOMAN])            # five joiners
    assert count_invisible(chain) == 2


def test_the_joiner_budget_resets_for_a_new_sequence():
    two = f"{MAN}{ZWJ}{WOMAN}{ZWJ}{GIRL}{ZWJ}{BOY}"
    assert count_invisible(two + " " + two) == 0
    assert count_invisible(two + two) == 0                            # adjacent: a new base starts a sequence


def test_braille_blank_counts_even_though_it_is_category_So():
    assert count_invisible("\u2800" * 3) == 3
    assert count_invisible(f"\u2800{VS16}") == 2                      # not treated as an emoji base


def test_the_exempt_positions_helper_returns_only_invisible_positions():
    from guardrails.match_view import INVISIBLE, exempt_positions
    text = f"a {HEART}{VS16}{ZWJ}{FIRE} {FLAG_ENGLAND} b"
    assert all(text[i] in INVISIBLE for i in exempt_positions(text))


# ---- the signal and the language gate (OI-077 interaction) ----

def test_joiners_in_a_non_latin_request_do_not_turn_a_language_refusal_into_a_charged_one():
    from guardrails.injection_screen import UNSUPPORTED_LANGUAGE, is_language_refusal_only
    persian = "\u0645\u0646 \u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645 \u0627\u06cc\u0646\u200c\u0637\u0648\u0631 \u0628\u067e\u0631\u0633\u0645 \u062e\u06cc\u0644\u06cc \u0633\u0627\u062f\u0647"
    assert persian.count(ZWNJ) >= 2
    r = screen_request(persian)
    assert r.matched_patterns == [UNSUPPORTED_LANGUAGE] and is_language_refusal_only(r)


def test_joiners_in_a_mostly_latin_request_are_still_counted():
    text = "Please read \u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645\u200c this and the report carefully"
    assert verdict(text) == ScreenVerdict.SUSPICIOUS


# ---- known limit, kept visible ----

@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="LIMIT: emoji pairs joined by ZWJ look well-formed without emoji data, so a message that "
                          "encodes bits as 'ZWJ or no ZWJ' between symbol pairs is not detected (CP-002 section 7)")
def test_LIMIT_a_zwj_bit_channel_between_emoji_pairs_is_not_detected():
    bits = "1011001110100101"
    text = " ".join(f"{SMILE}{ZWJ if b == '1' else ''}{SMILE}" for b in bits)
    assert verdict(text) == ScreenVerdict.SUSPICIOUS
