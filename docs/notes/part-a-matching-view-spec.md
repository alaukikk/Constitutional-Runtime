# Part A — Stage 0/1 Matching View (Proposal)

**Status: Proposed for owner review. Not implemented.** This document records a candidate design and review recommendations; it does not amend the frozen architecture, authorize code changes, or claim that the identified findings are closed.

Related open items: OI-080 (Stage 0 normalization/matching defects), OI-081 (Stage 1 keyword matching). Related evidence: F-01, F-02, F-03, F-05. F-04 and F-06 remain outside Part A.

## Purpose and boundary

Introduce a derived matching view used only when deciding whether a Stage 0 pattern or Stage 1 policy keyword matches. The view is built from the raw request because the existing v1 normalization may already delete separators before Stage 1 sees the text.

The intended boundary is:

- Stage 0/1 detection may inspect the proposed derived matching view.
- The text passed to tiers, cache key, confirmation-token binding, and CP-001 audit digest continue to use the existing v1 normalized text.
- `NORMALIZATION_VERSION` remains `"1"`; the v1 golden test and digest semantics are unchanged by Part A.
- `config/constitution.yaml` is not edited; Stage 1 keywords are canonicalized at engine load using the same matching-view rules.
- The view is detection-only. It does not rewrite the user's tier-bound text or establish that the request is safe.

This separation preserves the existing normalized representation for routing/execution and audit evidence, but it creates a known representation difference: a gate may detect a pattern in the matching view while the plan/classifier still sees v1 text. That limitation must remain explicit.

## Proposed transformations

The exact character inventory and mapping table must be reviewed alongside the implementation before approval.

1. **Separators:** the enumerated whitespace/separator characters become a space or newline according to the proposed table, rather than being allowed to fuse adjacent words.
2. **Hyphens and underscores:** the enumerated hyphen-like characters and underscore become a space.
3. **Apostrophes:** enumerated apostrophe variants are deleted in the matching view so forms such as `dont`, `don't`, and `don’t` can compare consistently.
4. **Confusables:** a curated table of approximately 26 look-alike letters folds to Latin in the matching view only. This is a bounded table, not comprehensive Unicode confusable detection.
5. **Invisible characters:** matching is attempted against two variants—one with enumerated invisible characters deleted and one with them replaced by a space. A match in either variant counts. This aims to cover cases such as an invisible character splitting a keyword without requiring the detector to guess whether the character is intentional.
6. **Keyword canonicalization:** Stage 1 policy keywords are canonicalized under the same rules when the policy engine loads them. The constitution file remains unchanged.

The final reviewed spec/implementation should enumerate the exact code points, newline/space handling, confusable mappings, and ordering of transformations. “Approximately 26” is a design summary, not an acceptable substitute for the concrete table in code review.

## F-05 repeated-invisible-character signal

The proposal revives the `repeated_zero_width` signal by evaluating the matching view before invisible characters are lost. The proposed threshold is two or more enumerated invisible characters outside an emoji context.

The threshold and emoji exemption are provisional until boundary tests and the complete character table have been reviewed. Tests should include a family emoji sequence, `❤️`, one leading byte-order mark, multiple invisible characters in ordinary text, and invisible characters adjacent to emoji and ordinary text. The exemption should be narrow and must not suppress a suspicious signal merely because an invisible character occurs near an emoji.

A separate `mixed_script_token` signal is recommended for visibility into mixed-script tokens, but mixed script alone must not be described as proof of malicious intent. Legitimate multilingual names/text need regression coverage. Whether to include this optional signal remains an owner decision.

## Acceptance evidence proposed

The implementation PR should include named tests for F-01, F-02, F-03, and F-05, and the spec's regression set R-01 through R-07.

- **R-01 — Superset property:** for the fixed existing corpus, the new matching gates do not remove detections produced by the current matching behavior. This is a bounded corpus property, not proof that every additional match is desirable.
- **R-02 — Benign corpus:** a hand-written benign corpus checks false positives introduced by canonicalization.
- **R-03–R-07:** retain the explicitly named regression cases in the implementation PR/spec and ensure they cover transformation boundaries, emoji/invisible interactions, policy keyword matching, and existing behavior.
- Each of F-01, F-02, F-03, and F-05 must have direct, named assertions for the specific input and expected outcome, plus legitimate-text regression cases.
- Remove the corresponding strict xfail markers only in the same implementation PR that adds and verifies the passing assertions. Any stale marker should fail loudly.
- Test failures in the matching-view builder and both Stage 0 and Stage 1 call paths; verify security-relevant errors follow the runtime's existing failure semantics.

A monotonic/superset test alone is insufficient: a matching view can add detections and still introduce false positives. CI success means the specified tests passed, not that the runtime is generally injection-robust.

## Explicit residual limitations

- **F-04 remains open.** Variation selectors, combining grapheme joiner (CGJ), Braille blank, and Hangul filler characters that survive v1 are not stripped from downstream tier text by Part A. Tag characters are already removed by v1 because they are non-printable; this distinction should not be conflated with F-04.
- **F-06 remains open.** Pattern-only Stage 0 screening does not cover all paraphrases, leetspeak, base64, or split-instruction attacks.
- Punctuation forms outside the explicit separator table (for example, commas between words), punctuation around terms such as `ssn :`, and homoglyphs outside the curated table remain visible limitations and should remain represented by targeted xfails where the harness currently records them.
- Plan and classifier inputs remain v1 text. Detection and downstream routing can therefore observe different representations.
- Part A does not justify claims of general obfuscation resistance, injection robustness, multilingual safety, or production readiness.
- Part A does not decide whether downstream model input must be stripped of F-04 characters. That is the separate Part B question and may instead be handled by refusal/hold-on-detection, subject to explicit design review and legitimate-text evidence.

## Governance and review questions

- Review the complete separator, invisible-character, and confusable tables before approving implementation.
- Treat the threshold of two and emoji exemption as provisional until the stated boundary tests are reviewed.
- The recommendation is to include `mixed_script_token` as a separate SUSPICIOUS signal, with explicit false-positive tests and no claim that mixed script alone proves intent; owner approval is pending.
- Keeping plan/classifier input on v1 text is recommended for this bounded change, provided the representation mismatch remains an explicit limitation and is revisited before broader security claims.
- `policy/engine.py` is code-owner governed. An optional parameter on `PolicyEngine.evaluate()` may still be a shared callable-interface change even if `policy/schemas.py` and return types remain unchanged. Check the Development Constitution and precedent before implementation; if ambiguous, resolve the Change Proposal question explicitly rather than assuming an exemption.
- Changes under `policy/` must follow the policy-governance and code-owner review path. This documentation does not itself authorize a code change.

## Permitted claim after implementation

If the specified tests pass and the corresponding xfails are removed, the bounded claim is:

> F-01, F-02, F-03, and F-05 are addressed for the enumerated character classes and tested inputs in the matching-view test corpus.

Do not shorten that to “robust to obfuscation” or “injection-robust.”
