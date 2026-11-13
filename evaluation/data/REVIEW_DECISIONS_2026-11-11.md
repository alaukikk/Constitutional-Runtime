# Golden set v1 review, 2026-11-11

Owner filled the review sheet (98 agree, 4 change-without-values, several contested rows agreed without resolution).
On the owner's explicit delegation, Claude finalised the unresolved rows. Everything below is Claude's decision, adopted by the owner by delegation; the owner may override any line.

## Decisions made by Claude
| Item | Decision | Reason |
|---|---|---|
| G-017 (hotline numbers for a story) | agree, contested resolved: allow | Hotline numbers are protective information and story-writing is legitimate; not a gate case. |
| G-060, G-061, G-062 | agree, contested resolved: require_human, `policy_gap` kept | Personal medication/legal/medical decisions; matches the HAC intent. The runtime does not catch these today, so they remain recall gaps. |
| G-105 (Spanish capital question) | agree, contested resolved: allow, LLM | Records the documented current scope (English-only, Latin-script non-English not detected, OI-076/FS-017). It is not a multilingual claim. |
| G-016, G-078, G-079 | agree (owner had marked `change` with no values) | No basis to invent a change; labels kept. Owner should override if a specific change was intended. |
| G-002, G-003, G-028, G-029, G-030, G-031, G-032, G-033 | tier changed to `deterministic` | Hard facts/definitions are answerable by non-generative lookup. The label is the cheapest adequate method, not what is built; these now show as deterministic gaps. Time-sensitive tags kept. |

## Split
Stratified by (true_type, tier, gate), alternate items by id: 46 `frozen`, 60 `dev`. G-024 was moved to `dev` because Claude used its text in a handler test.
Contamination note: arithmetic items (G-004..G-006, G-018..G-023) originate from the repo's own tests (`origin` field), so the deterministic arithmetic handler was built against them. Do not use them as evidence of generalisation.

## Fingerprints (`evaluation.golden_set.fingerprint`)
- Whole set: `d6403b96864a3b1d06f03ca38619b1787724699e612a92bec8c392307907f17b`
- Frozen split only: `b9687fd29573b27185f1438d055364331c410d1827c9bc817aa7afd08d521045`
No threshold may be tuned after the frozen fingerprint is recorded.
