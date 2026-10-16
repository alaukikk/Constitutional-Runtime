# CP-002: Matching view for Stage 0 / Stage 1 pattern matching (Part A)

**Status:** ACCEPTED by project owner on 2026-10-17; implementation not yet authorized by this document alone.
**Author:** Claude (implementation analysis). **Decider:** project owner under Rule 4.
**Date:** 2026-10-17
**Basis:** Part A matching-view specification and review findings RF-1 through RF-8. This record captures the owner's explicit approval of D-1 through D-7.

---

## 0. Why this is a Change Proposal

This proposal changes stage inputs and outputs. Stage 0's declared output is normalized text plus verdict and confidence; adding `match_views` changes that output. Stage 1's declared input is normalized text plus Stage 0 verdict; accepting a second representation changes that input. This is therefore an architecture change even if the `policy/schemas.py` shared data shape is not changed. CP-001 is precedent for governance of shared-shape changes; OI-017 is not contrary evidence because its record does not establish that this security-boundary question was considered.

## 1. Summary

Add a **matching view**: a derived string used only to decide whether a Stage 0 pattern or Stage 1 keyword matches. Build it from raw request text because `_normalize` has already deleted separator information. It is never sent to a tier, cached, digested, logged, or used in the confirmation token. Matching is the OR of the v1 normalized text and the views, so Part A can only add matches relative to v1.

Part A does not change `_normalize`, `NORMALIZATION_VERSION`, audit digests, or the text sent to a tier. F-04 and F-06 are not addressed and their strict xfails stay. Part B (what the model receives) is a separate decision.

## 2. Change proposal

**Component:** Stage 0 (`guardrails/injection_screen.py`, new `guardrails/match_view.py`), Stage 1 (`policy/engine.py`), wiring in `api/main.py`.

**Current behavior:** Stage 0 patterns run on `_normalize(raw).lower()`. Stage 1 does `kw.lower() in normalized.lower()`. The current normalization can delete separators and fuse words; curly apostrophes, hyphens and look-alike letters can defeat keywords and patterns (F-01, F-02, F-03). The `repeated_zero_width` signal is dead because the relevant characters have already been stripped (F-05).

**Approved direction:** add a derived matching view as specified in Appendices A–C. `ScreenResult` gains one trailing optional `match_views` field (default empty). `PolicyEngine.evaluate(normalized_text, match_views=None)`; `None` means v1-only matching, identical to current behavior. Stage 0 and Stage 1 evaluate v1 first, then the views, and union the matches. `repeated_zero_width` is revived as a SUSPICIOUS signal. `config/constitution.yaml` is not edited; keywords are canonicalized at engine load. `mixed_script_token` is deferred and is not part of this proposal.

**Why necessary**
1. **Research:** trace to the existing `guardrails/injection_screen.py` entry in `RESEARCH_TRACEABILITY.md` and the project's OWASP LLM01 materials. This proposal makes no new research claim; source-specific claims must be independently checked against the source material before publication.
2. **Security:** nine findings F-01 to F-09 were identified; the 32 strict xfails cover F-01 to F-08. This proposal targets F-01, F-02, F-03 and F-05 for the explicitly listed character classes only.
3. **Engineering:** a derived view is additive and confined; it avoids altering `NORMALIZATION_VERSION`, audit digests, cache keys or tier input.
4. **Resource efficiency:** pure string operations, no AI, no new store. Measure overhead using the existing runtime-overhead accounting (`breakeven.py`) rather than assuming it is negligible.

**Existing components affected:** `guardrails/injection_screen.py`, `policy/engine.py` (CODEOWNERS review required), `api/main.py`, new `guardrails/match_view.py`, tests, `ARCHITECTURE.md`, and `OPEN_ENDS.md` (OI-080, OI-081).

**Governance classification**
- [x] Architecture: Stage 0 output and Stage 1 input change.
- [x] Runtime-constitution semantics: the file is untouched, but keyword matching semantics broaden.
- [x] Evaluation methodology: benign corpus and new-match review required.
- [ ] Stage ordering/escalation path changes.
- [ ] `policy/schemas.py` shared data shape change.

**What breaks if this is not done?** F-01, F-02, F-03 and F-05 remain open, and Stage 0/1 remain vulnerable to the listed whitespace, punctuation, look-alike and invisible-character variants.

## 3. Approved architecture wording

- **Stage 0 #3 Output:** “Normalized text + a screen verdict + confidence score + derived matching views (used only for pattern matching; never persisted, cached, digested, or passed to a tier).”
- **Stage 1 #2 Input:** “Normalized text + Stage 0 verdict + (optionally) Stage 0 matching views. With no views supplied, matching is on normalized text only.”
- **Core principle, add:** “The security gates may evaluate derived matching views of the request. Everything downstream of the gates (classifier, tier, cache, confirmation token, audit digest) continues to use the normalized text. The text a model receives is therefore not equivalent to the text the gates evaluated, and gate decisions are not a guarantee about what the model reads.”
- Stage 0 #12 / Stage 1 #12 add benign-corpus and new-match review requirements.

The document remains **FROZEN**; the accepted proposal is the governance trail for this narrow wording change. The status must not be represented as implementation or verification.

## 4. Required revisions from review (RF-1–RF-8)

**RF-1 — Emoji exemption must not be adjacency-based.** Exempt only well-formed sequences: U+200D only within a valid emoji ZWJ sequence; U+FE0F/U+FE0E only immediately after an emoji-capable base (or digit, `#`, `*` for keycap), at most one per base; subdivision tag sequences only in the exact black-flag + tag letters + cancel-tag form with a length cap. Everything else counts.

**RF-2 — Preserve subdivision flags.** England, Scotland and Wales flags use six tag characters (Cf). Add an explicit benign test; the narrowed rule must not false-positive them.

**RF-3 — Pasted-text false positives.** Zero-width spaces and soft hyphens occur in web/PDF copy. Two signals can make a request SUSPICIOUS (+2 risk); the session `require_human_risk` threshold is 4.0 with no decay (OI-019), so ordinary pasted requests could accumulate risk. Include pasted-text samples and measure outcomes. Threshold 2 remains provisional until reviewed.

**RF-4 — Pin Unicode behavior.** Commit explicit reviewed codepoint tables for set I, line breaks, Zs, hyphen-likes and apostrophes. Add a drift test comparing committed tables to runtime `unicodedata`, failing with a review-required message. Category checks remain only for emoji context and are covered by golden tests.

**RF-5 — Prevent silent wiring fallback.** Add a wiring test asserting the pipeline passes the screen result's views to `evaluate`. `None` remains valid for direct callers/tests; wrong types raise `TypeError` and the pipeline fails closed.

**RF-6 — Preserve v1 matches on view failure.** Run v1 matching first and retain its result. If view matching raises, existing per-rule failure behavior applies: fail-closed rules escalate to BLOCK; fail-open rules log a warning and retain the v1 result. Stage 0 remains fail-closed on view-builder errors.

**RF-7 — Document residuals.** Include LIMIT xfails or explicit residuals for combining marks inserted inside words (e.g. `i` + U+0301 + `gnore`), Cyrillic letters outside the table (к, м, т, н, в and others), further apostrophe-likes (U+201B, U+2035, U+02B9, U+02C8, U+055A), further hyphen-likes (U+058A, U+05BE, U+1806, U+2043), and dotted-capital-I lowercase expansion.

**RF-8 — Audit broadened matches.** Deleting single quotes means `'ignore' 'all' 'previous' 'instructions'` becomes a match. This may be desirable but is a new match class and must appear in the new-match review.

## 5. Acceptance tests required before claiming implementation complete

**N-01 New-match audit.** Keep the v1-superset property as a safety property, but recognize it is true by construction and does not prove new matches are appropriate. Generate a report of each (input, rule, view) matching under views but not v1 across the benign corpus and existing repository strings. Commit a snapshot. Every benign-corpus new match must have a written justification or the transformation must change; any new entry fails CI until reviewed. View-of-origin is recorded in the test report only, not the audit schema.

**N-02 Transformation tests.** For apostrophe deletion, hyphen-to-space, invisible strip, invisible-to-space and confusable folding, test adversarial inputs that must match and legitimate inputs that must not newly match (contractions, hyphenated compounds, code, Markdown rules, names with diacritics and quoted foreign words).

**N-03 Invisible/emoji boundaries.** Test interleaved emoji/invisible payload as SUSPICIOUS; one and two invisibles next to ordinary text at threshold 2; standalone variation selector counted; VS16 after emoji base exempt; forty variation selectors after one emoji SUSPICIOUS; family ZWJ, keycap, skin-tone emoji, regional-indicator flag and England subdivision flag CLEAN; invisible next to emoji but adjacent to a letter on the other side counted.

**N-04 Failure paths.** Stage 0 view-builder error gives BLOCKED `screen_internal_error`. Stage 1 view-matching error on fail-closed rule gives BLOCK; on fail-open rule logs warning and keeps v1 result. Existing v1 match survives view failure. Wrong-type `match_views` raises and pipeline fails closed. Test pipeline wiring.

**N-05 Unicode table drift.** Fail with a review-required message if committed tables differ from running `unicodedata`.

**N-06 Pasted-text sample.** Include at least 10 pasted-text samples with zero-width space, soft hyphen, NBSP and mixed whitespace. Record verdict, session risk added, and how many requests reach the require-human threshold. Threshold 2 is not calibrated until reviewed.

**N-07** is not required because `mixed_script_token` is deferred.

## 6. Claims allowed after Part A passes

Allowed: F-01, F-02, F-03 and F-05 are closed for listed character classes and tested inputs; matching can only add detections relative to v1; audit digests and `_normalize` output are unchanged; benign-corpus new matches are reported with justifications.

Not allowed: “Stage 0/1 are robust to obfuscation”; “invisible-character smuggling is solved” (F-04 remains open); any false-positive rate beyond the corpus; or any claim that the model receives what the gates evaluated.

OI-080 becomes “partially resolved (F-04 open)”. OI-081 may resolve only for the tested whitespace, hyphen and apostrophe handling, with residuals recorded.

## 7. Limitations that must remain visible

- Gates use matching views; the plan/classifier, tier, cache and token use v1 text. A request caught under a view may, if it passes, be classified from a different representation. Revisit before broader security claims.
- Text passed to the model is not equivalent to the text gates evaluated.
- Confusable folding is a curated table of 25 entries, not UTS #39.
- Without `mixed_script_token`, an out-of-table homoglyph has no signal of its own. Keep this as a visible LIMIT xfail.
- Other punctuation between words, leetspeak, paraphrase and encodings remain open (F-06 unchanged).
- F-04 characters (variation selectors, CGJ, Braille blank, Hangul fillers) still reach the model.

## Appendix A — Transformation rules

Order of application to raw string. `flat_strip` and `flat_space` use rules 1–8; `lines` uses rules 1–7 with newlines kept and invisibles deleted; keywords are canonicalized with `flat_strip`.

| # | Rule | Scope |
|---|---|---|
| 1 | NFKC | As v1 |
| 2 | Lowercase | |
| 3 | Line breaks to `\n` | CRLF, CR, U+000B, U+000C, U+0085, U+2028, U+2029 |
| 4 | Spaces to one space | Tab and Zs: U+0020, U+00A0, U+1680, U+2000–U+200A, U+202F, U+205F, U+3000; runs collapse; in flat views a run containing a line break becomes one space |
| 5 | Hyphen-likes to space | U+002D, U+005F, U+2010–U+2015, U+2212, U+FE58, U+FE63 |
| 6 | Apostrophes deleted | U+0027, U+2018, U+2019, U+02BC, U+2032, U+0060, U+00B4 |
| 7 | Confusables folded | Appendix B |
| 8 | Invisibles | Set I (Appendix C): `flat_strip` deletes; `flat_space` replaces with a space; a match in either counts |

Pattern/view assignment: `excessive_special_chars` stays on v1 text only; `nested_instruction_marker` uses v1 OR `lines`; `repeated_zero_width` uses raw NFKC text.

## Appendix B — Confusable table (25 entries)

Applied after lowercasing, in matching view only.

| Source | Codepoint | Folds to |
|---|---|---|
| Cyrillic а | U+0430 | a |
| Cyrillic с | U+0441 | c |
| Cyrillic е | U+0435 | e |
| Cyrillic о | U+043E | o |
| Cyrillic р | U+0440 | p |
| Cyrillic х | U+0445 | x |
| Cyrillic у | U+0443 | y |
| Cyrillic і | U+0456 | i |
| Cyrillic ј | U+0458 | j |
| Cyrillic ѕ | U+0455 | s |
| Cyrillic ԁ | U+0501 | d |
| Cyrillic һ | U+04BB | h |
| Cyrillic ӏ | U+04CF | l |
| Cyrillic ԛ | U+051B | q |
| Cyrillic ԝ | U+051D | w |
| Greek α | U+03B1 | a |
| Greek ο | U+03BF | o |
| Greek ν | U+03BD | v |
| Greek ρ | U+03C1 | p |
| Greek ι | U+03B9 | i |
| Greek κ | U+03BA | k |
| Greek υ | U+03C5 | u |
| Greek χ | U+03C7 | x |
| Greek ε | U+03B5 | e |
| Latin ı (dotless i) | U+0131 | i |

Residuals include Cyrillic к, м, т, н, в and others; combining-mark insertion; and scripts outside Cyrillic and Greek. The unsupported-script gate keeps seeing unfolded text. Greek τ→t is excluded per D-7.

## Appendix C — Invisible set I and smuggling signal

Set I: category Cf (including U+00AD, U+200B–U+200F, U+202A–U+202E, U+2060–U+2064, U+2066–U+206F, U+FEFF, U+FFF9–U+FFFB, U+E0001, U+E0020–U+E007F), U+FE00–U+FE0F, U+E0100–U+E01EF, U+034F, U+115F, U+1160, U+3164, U+FFA0, U+2800, U+180E. Implementation must commit this as an explicit generated table, not rely on a category check for set membership.

`repeated_zero_width`: count set-I characters in raw NFKC text that are not part of an exempt well-formed emoji sequence (RF-1). SUSPICIOUS when count is at least 2. Threshold 2 is provisional [JUDGMENT]; revisit after N-06 and the R-02 corpus.

## Part D — Owner decisions (2026-10-17)

The project owner explicitly approved D-1 through D-7 on 2026-10-17.

| ID | Decision | Status |
|---|---|---|
| D-1 | Approve matching-view approach in principle, subject to acceptance tests. Confine view to Stage 0/1 matching; preserve v1 normalization, cache keys, audit digests, confirmation binding and tier input. Acceptance depends on adversarial and benign-corpus checks, not superset property alone. | ACCEPTED |
| D-2 | Keep invisible threshold 2 provisionally. Accept RF-1 well-formed emoji exemptions. Require N-03 and N-06 before calling threshold calibrated; record verdicts and risk implications. | ACCEPTED |
| D-3 | Defer `mixed_script_token` until token boundaries, script combinations, Unicode handling and benign-name expectations are specified. Track in future scope. | ACCEPTED |
| D-4 | Accept v1 downstream text as an explicit temporary limitation; revisit before broader security claims or reliance on real-LLM integration. Do not imply model receives what gates evaluated. | ACCEPTED |
| D-5 | Require CP governance for this stage input/output change. Clarify that “interface” includes cross-stage inputs, outputs and security-relevant representations, not only shared schemas. | ACCEPTED |
| D-6 | Accept RF-1 through RF-8 as required revisions with testable criteria: preserve v1 match on view failure, test pipeline wiring, pin explicit Unicode tables, perform new-match audit, and justify/remove each benign-corpus new match. | ACCEPTED |
| D-7 | Drop Greek τ→t from the initial table; reconsider later only with specific adversarial and benign examples. | ACCEPTED |

**Implementation boundary:** Acceptance records architectural authorization for the proposal, not implementation completion. The implementation PR must satisfy the acceptance tests above, receive required CODEOWNERS review, and report test results accurately. No implementation or test success is claimed by this document.
