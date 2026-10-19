
"""
Matching views for Stage 0 / Stage 1 (CP-002, Part A).

WHAT THIS IS
A "matching view" is a DERIVED string used ONLY to decide whether a Stage 0 pattern or a Stage 1
keyword matches. It is built from the RAW request, because Stage 0's _normalize() has already
thrown the separator information away (it deletes every non-printable character, so a tab or a
zero-width space used as a word separator fuses the neighbouring words).

CONFINEMENT (CP-002 D-1, D-4)
A view is never sent to a tier, never cached, never digested, never logged and never used in the
confirmation token. The plan/classifier, the tier, the cache key, the token and the audit digest keep
using the v1 normalized text exactly as before. Matching is the OR of the v1 text and the views, so
this change can only ADD matches compared with v1, never remove one.

THE TEXT THE MODEL RECEIVES IS NOT THE TEXT THE GATES EVALUATED. Passing Stage 0/1 is not a guarantee
about what the model reads (explicit, accepted limitation; revisit before broader security claims).

WHAT IS PINNED (CP-002 RF-4)
Every character table below is an explicit, reviewed list of code points, not a Unicode-category
check, so a Python upgrade cannot silently change behaviour. tests/guardrails/test_match_view_tables.py
compares the Cf and Zs tables with the running interpreter's unicodedata and fails with a
"review required" message when they differ. The emoji-context checks (categories So / Sk) are the only
category-based logic left; they are pinned by golden tests.

DEVIATIONS FROM THE CP-002 APPENDIX TEXT (found while implementing; each one is covered by a test)
  1. U+00B4 (acute accent) is rewritten to an apostrophe BEFORE NFKC. NFKC turns U+00B4 into
     "SPACE + U+0301", so rule 6 ("U+00B4 deleted") could never see it after rule 1.
  2. The `lines` view (used only by nested_instruction_marker) applies rules 1-4, 7 and invisible
     deletion, but NOT hyphen-to-space (5) or apostrophe deletion (6). With rule 5 a markdown bullet
     such as "- system: Linux" would become " system: Linux" and be BLOCKED as a fake conversation
     turn (a benign new match; CP-002 N-01 / D-6 require such a match to be removed or justified).
     Neither rule is needed to find a role marker.

KNOWN RESIDUALS (kept visible, see the LIMIT tests and CP-002 section 7)
  * Control characters (Cc) other than tab / the listed line breaks are not separators here. v1 deletes
    them, so "ignore\\x00all\\x00previous\\x00instructions" still fuses (proposed finding F-10).
  * The emoji exemption cannot tell a real emoji sequence from a look-alike one without emoji data
    (not in the standard library): ZWJ between two symbols is exempt, up to three ZWJ per sequence.
    A message that encodes bits as "ZWJ or no ZWJ" between symbol pairs is not detected.
  * Homoglyphs outside the 25-entry table, combining marks inside words, other punctuation between
    words, leetspeak, paraphrase and encodings are not handled (F-06 unchanged).
No AI, no model call, pure and deterministic.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Unicode version the generated tables below were produced from (Python 3.13 -> 15.1.0).
PINNED_UNICODE_VERSION = "15.1.0"


def _chars(ranges: tuple[tuple[int, int], ...]) -> frozenset[str]:
    return frozenset(chr(cp) for lo, hi in ranges for cp in range(lo, hi + 1))


# --------------------------------------------------------------------------------------------------
# Explicit tables (RF-4). Cf = unicodedata category "Cf" generated on Unicode 15.1.0 (170 code points).
# --------------------------------------------------------------------------------------------------
CF_RANGES: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD), (0x0600, 0x0605), (0x061C, 0x061C), (0x06DD, 0x06DD), (0x070F, 0x070F),
    (0x0890, 0x0891), (0x08E2, 0x08E2), (0x180E, 0x180E), (0x200B, 0x200F), (0x202A, 0x202E),
    (0x2060, 0x2064), (0x2066, 0x206F), (0xFEFF, 0xFEFF), (0xFFF9, 0xFFFB), (0x110BD, 0x110BD),
    (0x110CD, 0x110CD), (0x13430, 0x1343F), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001), (0xE0020, 0xE007F),
)

# Invisible carriers outside Cf that normalization keeps (CP-002 Appendix C): combining grapheme
# joiner, Hangul fillers, Braille blank, variation selectors and supplementary variation selectors.
EXTRA_INVISIBLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x034F, 0x034F), (0x115F, 0x1160), (0x2800, 0x2800), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xE0100, 0xE01EF),
)

# Set I: characters a human cannot see.
INVISIBLE: frozenset[str] = _chars(CF_RANGES) | _chars(EXTRA_INVISIBLE_RANGES)

# Zs on Unicode 15.1.0 (17 code points).
ZS_RANGES: tuple[tuple[int, int], ...] = (
    (0x0020, 0x0020), (0x00A0, 0x00A0), (0x1680, 0x1680), (0x2000, 0x200A),
    (0x202F, 0x202F), (0x205F, 0x205F), (0x3000, 0x3000),
)
ZS: frozenset[str] = _chars(ZS_RANGES)

# Line breaks (rule 3): \n \r VT FF NEL LS PS. CRLF collapses to one break by the run logic.
LINE_BREAKS: frozenset[str] = frozenset("\n\r\x0b\x0c\x85\u2028\u2029")

# Rule 5: hyphen-likes become a space (flat views only).
HYPHEN_LIKES: frozenset[str] = _chars(
    ((0x002D, 0x002D), (0x005F, 0x005F), (0x2010, 0x2015), (0x2212, 0x2212), (0xFE58, 0xFE58), (0xFE63, 0xFE63))
)

# Rule 6: apostrophes are DELETED (not folded), so dont / don't / don’t all become "dont".
# U+00B4 is handled before NFKC (see the module docstring, deviation 1).
APOSTROPHES: frozenset[str] = _chars(
    ((0x0027, 0x0027), (0x0060, 0x0060), (0x00B4, 0x00B4), (0x02BC, 0x02BC), (0x2018, 0x2019), (0x2032, 0x2032))
)

# Rule 7: confusables folded to Latin. Curated, letters only, lower-case side (25 entries; Greek tau
# was dropped by decision D-7). NOT UTS #39: the standard library has no confusables data.
CONFUSABLES: dict[str, str] = {
    # Cyrillic
    "\u0430": "a", "\u0441": "c", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0445": "x",
    "\u0443": "y", "\u0456": "i", "\u0458": "j", "\u0455": "s", "\u0501": "d", "\u04bb": "h",
    "\u04cf": "l", "\u051b": "q", "\u051d": "w",
    # Greek
    "\u03b1": "a", "\u03bf": "o", "\u03bd": "v", "\u03c1": "p", "\u03b9": "i", "\u03ba": "k",
    "\u03c5": "u", "\u03c7": "x", "\u03b5": "e",
    # Latin look-alike NFKC leaves alone
    "\u0131": "i",
}

# --------------------------------------------------------------------------------------------------
# Emoji context for the invisible-character count (RF-1 / RF-2).
# --------------------------------------------------------------------------------------------------
ZWJ = "\u200d"
VS15 = "\ufe0e"
VS16 = "\ufe0f"
BLACK_FLAG = "\U0001F3F4"
CANCEL_TAG = "\U000E007F"
# Tag digits and tag letters: the body of a subdivision flag (England = gbeng, Scotland = gbsct).
TAG_BODY: frozenset[str] = _chars(((0xE0030, 0xE0039), (0xE0061, 0xE007A)))
# Emoji whose base is not category So (text-default emoji that take VS16).
EMOJI_BASE_EXTRA: frozenset[str] = frozenset("\u203c\u2049\u2139\u2194\u3030\u303d")
KEYCAP_BASES: frozenset[str] = frozenset("0123456789#*")
MAX_ZWJ_PER_SEQUENCE = 3            # the longest RGI emoji ZWJ sequences have three joiners
SUBDIVISION_TAG_MIN, SUBDIVISION_TAG_MAX = 2, 8


def _is_emoji_symbol(ch: str) -> bool:
    """An emoji-capable symbol: category So (never an invisible one, e.g. the Braille blank) or a
    small explicit list of text-default emoji. Category-based, so pinned by golden tests."""
    return (unicodedata.category(ch) == "So" and ch not in INVISIBLE) or ch in EMOJI_BASE_EXTRA


def _is_vs_base(ch: str) -> bool:
    """A character a variation selector may legitimately follow: an emoji symbol, a skin-tone
    modifier (Sk) or a keycap base (digit, #, *)."""
    return _is_emoji_symbol(ch) or unicodedata.category(ch) == "Sk" or ch in KEYCAP_BASES


def exempt_positions(text: str) -> set[int]:
    """Indexes of invisible characters that are part of a WELL-FORMED emoji sequence and therefore
    not counted (RF-1). Adjacency to an emoji is NOT enough: an attacker can interleave emoji and
    invisible characters, so only these exact shapes are exempt:
      * VS15/VS16 immediately after an emoji base, a skin-tone modifier or a keycap base, at most one
        per base (a second selector follows a selector, not a base, so it counts);
      * ZWJ between two emoji symbols (the previous one may carry its VS16), at most three per sequence;
      * a subdivision-flag tag sequence: U+1F3F4, 2-8 tag digits/letters, then the cancel tag.
    Everything else (ZWSP, ZWNJ, BOM, soft hyphen, bidi controls, stray tags, a ZWJ next to a letter,
    selectors after a letter, ...) counts."""
    exempt: set[int] = set()
    n = len(text)
    chain = 0                       # exempt ZWJ already used in the current emoji sequence
    for i, ch in enumerate(text):
        prev = text[i - 1] if i else ""
        if ch == BLACK_FLAG:
            j = i + 1
            while j < n and text[j] in TAG_BODY:
                j += 1
            if SUBDIVISION_TAG_MIN <= j - (i + 1) <= SUBDIVISION_TAG_MAX and j < n and text[j] == CANCEL_TAG:
                exempt.update(range(i + 1, j + 1))
        elif ch in (VS15, VS16):
            if prev and _is_vs_base(prev):
                exempt.add(i)
        elif ch == ZWJ:
            joined_left = bool(prev) and (_is_emoji_symbol(prev) or unicodedata.category(prev) == "Sk"
                                          or (prev == VS16 and (i - 1) in exempt))
            joined_right = i + 1 < n and _is_emoji_symbol(text[i + 1])
            if joined_left and joined_right and chain < MAX_ZWJ_PER_SEQUENCE:
                exempt.add(i)
                chain += 1
            continue                # a ZWJ never resets the sequence
        # Sequence bookkeeping: a new emoji symbol that does not follow a ZWJ starts a new sequence;
        # anything that is not part of an emoji sequence ends it.
        if _is_emoji_symbol(ch):
            if prev != ZWJ:
                chain = 0
        elif ch in (VS15, VS16) or unicodedata.category(ch) == "Sk":
            pass
        else:
            chain = 0
    return exempt


def count_invisible(raw_text: str) -> int:
    """Number of set-I characters in the raw NFKC text that are NOT part of a well-formed emoji
    sequence. This is the `repeated_zero_width` signal (SUSPICIOUS at >= 2, provisional)."""
    text = unicodedata.normalize("NFKC", raw_text)
    exempt = exempt_positions(text)
    return sum(1 for i, ch in enumerate(text) if ch in INVISIBLE and i not in exempt)


# --------------------------------------------------------------------------------------------------
# The views.
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MatchViews:
    """flat_strip: invisibles deleted (intra-word insertion). flat_space: invisibles become a space
    (separator use). lines: newlines kept, only for nested_instruction_marker. A match in ANY view,
    or in the v1 text, counts."""
    flat_strip: str
    flat_space: str
    lines: str

    def __post_init__(self) -> None:
        for name in ("flat_strip", "flat_space", "lines"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"MatchViews.{name} must be str")

    @property
    def flat(self) -> tuple[str, str]:
        return (self.flat_strip, self.flat_space)


def _build(text: str, *, invisible_as_space: bool, flat: bool) -> str:
    """One pass over NFKC-lowercased text. Whitespace-like characters make a pending separator that
    is emitted before the next visible character, so runs collapse to one separator, leading and
    trailing ones vanish and (in the `lines` view) a run containing a line break becomes one newline.
    Deleted characters (apostrophes, stripped invisibles) do not interrupt a pending separator."""
    out: list[str] = []
    pending = ""
    for ch in text:
        if ch in LINE_BREAKS:
            sep = " " if flat else "\n"
        elif ch == "\t" or ch in ZS:
            sep = " "
        elif flat and ch in HYPHEN_LIKES:
            sep = " "
        elif ch in INVISIBLE:
            if not invisible_as_space:
                continue
            sep = " "
        elif flat and ch in APOSTROPHES:
            continue
        else:
            if pending and out:
                out.append(pending)
            pending = ""
            out.append(CONFUSABLES.get(ch, ch))
            continue
        pending = "\n" if (pending == "\n" or sep == "\n") else " "
    return "".join(out)


def _prepare(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("match views are built from str")
    # U+00B4 would become SPACE + U+0301 under NFKC, so it is mapped first (module docstring, 1).
    return unicodedata.normalize("NFKC", raw.replace("\u00b4", "'")).lower()


def build_match_views(raw: str) -> MatchViews:
    """The Stage 0 / Stage 1 matching views of a RAW request (pure, deterministic, linear)."""
    text = _prepare(raw)
    return MatchViews(
        flat_strip=_build(text, invisible_as_space=False, flat=True),
        flat_space=_build(text, invisible_as_space=True, flat=True),
        lines=_build(text, invisible_as_space=False, flat=False),
    )


def canon_keyword(keyword: str) -> str:
    """A Stage 1 keyword in the same canonical form as flat_strip, so `don't ask me to confirm` in the
    YAML and `don\u2019t ask me to confirm` in a request meet at `dont ask me to confirm`. May return ""
    for a keyword made only of separators; callers must skip empty results (an empty string is a
    substring of everything)."""
    return _build(_prepare(keyword), invisible_as_space=False, flat=True)
