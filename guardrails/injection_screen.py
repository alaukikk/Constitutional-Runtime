



"""
Stage 0 — Minimal Trusted Ingress
Stateless, per-message jailbreak/injection screen. Runs before anything else,
with zero input from session history (see ARCHITECTURE.md core principle).
No AI permitted at this stage — regex/heuristic only.
Fails closed: any internal error => BLOCKED.

Unsupported-script refusal (OI-077). The runtime is scoped to English for now.
A request whose letters are mostly non-Latin script (Devanagari, Arabic,
Cyrillic, CJK, ...) is refused here: ScreenVerdict.BLOCKED with the single
matched pattern UNSUPPORTED_LANGUAGE. This stays inside Stage 0's contract:
deterministic character-class counting (no model), a pure function of the text,
fail-closed, and the verdict is still one of clean/suspicious/blocked.

What it CAN and CANNOT do (do not oversell it):
  * It detects non-LATIN SCRIPTS only. Romanised Hindi ("Hinglish"), Spanish,
    French and every other Latin-script language pass as ordinary text, because
    telling them from English needs language identification, which is a model
    and is not permitted at this stage. Those requests are still routed and
    still reach only English-keyword screens (OI-076, FS-017).
  * The rule is "most of the letters are non-Latin", not "contains a non-Latin
    letter": English that quotes a foreign word, a name, a math symbol or an
    emoji must not be refused. Thresholds below are [JUDGMENT] placeholders.

Session-risk boundary. This refusal is a scope decision, not a security signal,
so api/main.py does not charge session risk for it -- but ONLY when
UNSUPPORTED_LANGUAGE is the sole matched pattern (is_language_refusal_only).
If any injection or suspicious pattern also matches, the request takes the
normal path and is charged as before.

Matching views (CP-002, Part A). The patterns below are matched against the v1 normalized text AND
against derived matching views built from the RAW request (guardrails/match_view.py), so a tab, a
newline, a zero-width character, a hyphen, a typographic apostrophe or a look-alike letter between or
inside the words of a phrase no longer switches a pattern off. A match in any of them counts, so this
can only ADD detections. The views are used for matching only: ScreenResult.normalized_text, the
audit digest, the plan/classifier, the tier and the cache key are unchanged (NORMALIZATION_VERSION
stays "1"). The text a model receives is NOT the text the patterns were matched against. This closes
F-01, F-02, F-03 and F-05 for the character classes in match_view.py only; it is not general
obfuscation robustness (F-04 and F-06 are open).

Invisible-character signal (F-05). `repeated_zero_width` now counts invisible characters in the RAW
text (the old regex ran after _normalize() had deleted them, so it could never match) that are not
part of a well-formed emoji sequence; two or more make the request SUSPICIOUS. The threshold is a
provisional [JUDGMENT] value (CP-002 D-2). It is NOT added to an unsupported-script refusal
(OI-077): that refusal stays a scope decision, not a security signal, so a Persian or Hindi request
with joiner characters is not charged session risk for them.
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from guardrails.match_view import MatchViews, build_match_views, count_invisible


class ScreenVerdict(str, Enum):
    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    BLOCKED = "blocked"


@dataclass
class ScreenResult:
    normalized_text: str
    verdict: ScreenVerdict
    confidence: float
    matched_patterns: list[str]
    # CP-002: derived views for Stage 0/1 matching ONLY. Never persisted, cached, digested, logged or
    # sent to a tier. None for results that never reached pattern matching (empty, oversized, error).
    match_views: Optional[MatchViews] = None


# Grouped so the audit log can say *why*, not just *that*.
_BLOCK_PATTERNS: dict[str, str] = {
    "ignore_prior_instructions": r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
    "role_override": r"\byou\s+are\s+now\s+(in\s+)?(dan|jailbreak|developer\s+mode|unrestricted)\b",
    "system_prompt_exfil": r"\b(reveal|print|show|repeat)\s+(your\s+)?(system\s+prompt|instructions)\b",
    "pretend_no_rules": r"\bpretend\s+(you\s+have\s+)?no\s+(rules|restrictions|guidelines)\b",
    "override_safety": r"\b(disable|bypass|override)\s+(your\s+)?(safety|filters?|guardrails?)\b",
    # Only matches at the START of the text or right after a newline — mimicking
    # an injected fake conversation turn, not just the word appearing mid-sentence
    # (e.g. "the file system: works" must NOT match).
    "nested_instruction_marker": r"(?im)^\s*\[?\s*(system|assistant)\s*\]?\s*:\s*\S",
}

_SUSPICIOUS_PATTERNS: dict[str, str] = {
    "hypothetical_framing": r"\bhypothetically\b.{0,40}\b(if you (had|could)|no restrictions)\b",
    "encoding_then_execute": r"\b(base64|rot13|hex)\s+(encode|decode)\b.{0,60}\b(then|and)\s+(execute|run|follow)\b",
    "excessive_special_chars": r"[^\w\s]{15,}",
    # "repeated_zero_width" is NOT a regex any more: _normalize() deletes zero-width characters before
    # patterns run, so the old regex could never match (F-05). It is a count on the raw text, below.
}

# Which view each pattern is matched against, in addition to the v1 normalized text (CP-002 section 4).
#   flat  -> v1 OR flat_strip OR flat_space      lines -> v1 OR lines      v1 -> v1 text only
# Every pattern must be listed (a test enforces it) so adding one forces a decision here.
_PATTERN_VIEWS: dict[str, str] = {
    "ignore_prior_instructions": "flat",
    "role_override": "flat",
    "system_prompt_exfil": "flat",
    "pretend_no_rules": "flat",
    "override_safety": "flat",
    "nested_instruction_marker": "lines",
    "hypothetical_framing": "flat",
    "encoding_then_execute": "flat",
    # Hyphen-to-space would make a "-----------------" rule stop matching: v1 text only.
    "excessive_special_chars": "v1",
}

REPEATED_ZERO_WIDTH = "repeated_zero_width"
# [JUDGMENT] provisional (CP-002 D-2): this many non-emoji invisible characters make a request SUSPICIOUS.
_INVISIBLE_THRESHOLD = 2

_MAX_LEN = 20_000

# Version of the normalization applied by _normalize() (NFKC, then drop every non-printable
# character except newline, then strip). The audit log records it next to a request's salted
# HMAC (audit/request_evidence.py, CP-001), because a digest can only be matched against a
# reporter-supplied request if the SAME normalization is applied to it. If _normalize() ever
# changes behavior, bump this string in the same change; tests/guardrails/
# test_normalization_golden.py fails until the version and its golden outputs are updated
# together, so the change cannot happen unnoticed. Old records keep their old version.
NORMALIZATION_VERSION = "1"

# Marker pattern for the unsupported-script refusal (see module docstring).
UNSUPPORTED_LANGUAGE = "unsupported_language"

# [JUDGMENT] placeholders: refuse only when there are at least this many non-Latin
# letters AND they are STRICTLY more than this share of all letters. Exactly half
# passes, so a name with its native spelling next to it is not refused.
_MIN_NON_LATIN_LETTERS = 3
_NON_LATIN_MAJORITY = 0.5


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch == "\n" or ch.isprintable())
    return text.strip()


def _non_latin_letter_stats(text: str) -> tuple[int, int]:
    """(non-Latin letters, all letters). A letter counts as Latin when its Unicode
    name starts with LATIN, which covers accented forms (e-acute, n-tilde, ...).
    Digits, punctuation, symbols and emoji are not letters and are ignored."""
    non_latin = total = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total += 1
        try:
            name = unicodedata.name(ch)
        except ValueError:
            name = ""
        if not name.startswith("LATIN"):
            non_latin += 1
    return non_latin, total


def _is_unsupported_script(text: str) -> bool:
    non_latin, total = _non_latin_letter_stats(text)
    return (total > 0 and non_latin >= _MIN_NON_LATIN_LETTERS
            and non_latin / total > _NON_LATIN_MAJORITY)


def is_language_refusal_only(result: ScreenResult) -> bool:
    """True only for a BLOCKED result whose SOLE reason is the unsupported-script
    refusal. Anything else (an injection pattern, a suspicious pattern, an empty or
    oversized input, an internal error) is not exempt from normal handling."""
    return (result.verdict == ScreenVerdict.BLOCKED
            and list(result.matched_patterns) == [UNSUPPORTED_LANGUAGE])


def _pattern_hit(name: str, pattern: str, lowered: str, views: MatchViews) -> bool:
    """v1 first, then the views this pattern is assigned to. A view can only add a match."""
    if re.search(pattern, lowered):
        return True
    kind = _PATTERN_VIEWS[name]
    if kind == "flat":
        return any(re.search(pattern, text) for text in views.flat)
    if kind == "lines":
        return re.search(pattern, views.lines) is not None
    return False


def screen_request(request_text: str) -> ScreenResult:
    """Pure function of request_text alone — no session_id, no history."""
    try:
        if request_text is None:
            return ScreenResult("", ScreenVerdict.BLOCKED, 1.0, ["empty_input"])

        normalized = _normalize(request_text)
        if len(normalized) == 0:
            return ScreenResult(normalized, ScreenVerdict.BLOCKED, 1.0, ["empty_input"])
        if len(normalized) > _MAX_LEN:
            return ScreenResult(normalized[:_MAX_LEN], ScreenVerdict.BLOCKED, 1.0, ["oversized_input"])

        # CP-002: derived matching views, built from the RAW text. Any error here falls through to the
        # generic handler below: BLOCKED screen_internal_error (Stage 0 fails closed).
        views = build_match_views(request_text)
        lowered = normalized.lower()
        matched: list[str] = [name for name, pat in _BLOCK_PATTERNS.items()
                              if _pattern_hit(name, pat, lowered, views)]
        if matched:
            return ScreenResult(normalized, ScreenVerdict.BLOCKED, 0.9, matched, views)

        suspicious = [name for name, pat in _SUSPICIOUS_PATTERNS.items()
                      if _pattern_hit(name, pat, lowered, views)]
        smuggling = count_invisible(request_text) >= _INVISIBLE_THRESHOLD

        # Unsupported script: checked AFTER the injection patterns so an attack phrase is
        # never hidden behind this refusal, and any suspicious pattern is kept in the
        # result so the request is not treated as a language-only refusal.
        # The invisible-character signal does not join a language refusal (see the module docstring).
        if _is_unsupported_script(normalized):
            return ScreenResult(normalized, ScreenVerdict.BLOCKED, 0.9, [UNSUPPORTED_LANGUAGE] + suspicious, views)

        if smuggling:
            suspicious.append(REPEATED_ZERO_WIDTH)
        if suspicious:
            confidence = min(0.5 + 0.15 * len(suspicious), 0.85)
            return ScreenResult(normalized, ScreenVerdict.SUSPICIOUS, confidence, suspicious, views)

        return ScreenResult(normalized, ScreenVerdict.CLEAN, 0.95, [], views)

    except Exception:
        # Fail closed per ARCHITECTURE.md Stage 0 #7
        return ScreenResult("", ScreenVerdict.BLOCKED, 1.0, ["screen_internal_error"])
