# Draft taxonomy labels for golden set v1

`taxonomy_labels_v1_draft.jsonl` labels each of the 106 items in `golden_v1.jsonl` against `docs/TAXONOMY.MD` section 2 (Taxonomy B). It is a separate file; the golden set is not modified.

- Labeler: `claude-draft`; review: `draft`. Not owner-reviewed. Diagnostic use only (OI-011, OI-098).
- `taxonomy_tier` is the tier TAXONOMY.MD assigns to the subcategory. `golden_tier` is the golden set's `cheapest_adequate_tier`. They differ where a solver exists on paper but is not built or not reflected in the golden label.
- `n/a` rows are Stage 0/1 gate tests (22 items); their outcome is decided by the gate, not by structure. `GAP` rows have no taxonomy row (translation, code generation from a natural-language spec) and are candidates for new section 2 rows (no Change Proposal needed).

## Counts (106 items)

| Section / subcategory | Items |
|---|---|
| 2.1 Exact key-value lookup | 10 |
| 2.1 Semantic retrieval | 12 |
| 2.2 Basic arithmetic | 9 |
| 2.2 Unit conversion | 1 |
| 2.4 Exact string manipulation | 1 |
| 2.8 Statistical classification | 4 |
| 2.8 Semantic classification | 2 |
| 2.13 Document QA / grounded synthesis | 5 |
| 2.14 Ambiguous, under-specified | 22 |
| 2.14 Open-ended creative generation | 7 |
| 2.14 Stylistic/semantic rewriting | 2 |
| 2.15 UNKNOWN | 6 |
| GAP (no taxonomy row) | 3 |
| n/a (gate test items) | 22 |

## Where the taxonomy and the golden tier disagree (11 items)

- G-028, G-029, G-030, G-031 (static facts): taxonomy says a key-value table (deterministic); golden says `rag_small_model`. A fact table is the cheapest coverage-expansion candidate.
- G-105 (capital of France in Spanish) and G-100 (rename an identifier): taxonomy says deterministic; golden says LLM.
- G-043, G-073, G-102, G-104: taxonomy says retrieval/grounded; golden says LLM.
- G-071: taxonomy says ambiguous (LLM); golden says `rag_small_model`.

Deterministic-solvable on paper: 21 of 106 (13 routed there today), versus 22 gate items excluded. These are draft labels and one reading of the taxonomy.
