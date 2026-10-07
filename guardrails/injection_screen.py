
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
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


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
    "repeated_zero_width": r"[\u200b\u200c\u200d\ufeff]{2,}",
}

_MAX_LEN = 20_000

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

        lowered = normalized.lower()
        matched: list[str] = [name for name, pat in _BLOCK_PATTERNS.items() if re.search(pat, lowered)]
        if matched:
            return ScreenResult(normalized, ScreenVerdict.BLOCKED, 0.9, matched)

        suspicious = [name for name, pat in _SUSPICIOUS_PATTERNS.items() if re.search(pat, lowered)]

        # Unsupported script: checked AFTER the injection patterns so an attack phrase is
        # never hidden behind this refusal, and any suspicious pattern is kept in the
        # result so the request is not treated as a language-only refusal.
        if _is_unsupported_script(normalized):
            return ScreenResult(normalized, ScreenVerdict.BLOCKED, 0.9, [UNSUPPORTED_LANGUAGE] + suspicious)

        if suspicious:
            confidence = min(0.5 + 0.15 * len(suspicious), 0.85)
            return ScreenResult(normalized, ScreenVerdict.SUSPICIOUS, confidence, suspicious)

        return ScreenResult(normalized, ScreenVerdict.CLEAN, 0.95, [])

    except Exception:
        # Fail closed per ARCHITECTURE.md Stage 0 #7
        return ScreenResult("", ScreenVerdict.BLOCKED, 1.0, ["screen_internal_error"])
