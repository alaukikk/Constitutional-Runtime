# Problem & Capability Taxonomy — Reference Document

**Status:** Reference / implementation guidance. **Not an architecture document.**
**Governs:** the internal logic of `triage/taxonomy.py`, `triage/classifier.py`, and the
solver logic inside `tiers/deterministic.py`, `tiers/small_classifier.py`,
`tiers/rag_small_model.py`.
**Does not change:** any stage's inputs, outputs, ordering, or security boundary as
specified in `ARCHITECTURE.md`. Per `CONSTITUTION.md`, filling in stub logic with real
solvers is expected implementation progress, not a structural change — this document
does not require a Change Proposal.
**Out of scope (future work, deferred by explicit decision):** request decomposition —
splitting one compound request into multiple subproblems routed to different tiers in
parallel. Everything below assumes a single, classifiable request, consistent with
Stage 3's current interface.

---

## 0. Why this document exists

`ARCHITECTURE.md` Stage 3 already requires that a tier "may only be skipped with a
logged, documented reason" — silent default-to-LLM is already disallowed by the frozen
architecture. What was missing was a sufficiently detailed catalogue of *which*
conventional computational categories `triage/classifier.py` should be able to
recognize, and which solver family each one maps to, so that recognition-richness
doesn't quietly become the bottleneck even though the architecture itself has no
ceiling on it.

This document is deliberately organized as **four orthogonal taxonomies**, not one
flat list, because a single request's task, computational structure, required
capability, and correct execution mechanism are four different questions:

| Taxonomy | Question it answers | Where it's used |
|---|---|---|
| **A — Task type** | What is the user trying to accomplish? | `triage/taxonomy.py` (`RequestType`) |
| **B — Computational structure** | What kind of problem is it underneath the language? | `triage/classifier.py` internal logic |
| **C — Required capability** | What must the system be able to do to answer it? | `triage/decision.py` scoring inputs |
| **D — Execution mechanism** | What actually solves it, and at what tier? | `tiers/*.py` internal solver selection |

**Completeness guarantee.** No fixed list of categories can be proven exhaustive against
every future prompt (see §6). The actual completeness guarantee is architectural, not
enumerative: a request that doesn't match any registered category in Taxonomy B must be
logged as an explicit `UNKNOWN` computational structure and still pass through the
normal cheapest-first tier ladder rather than being fast-tracked to the LLM tier by
default. `UNKNOWN` is a first-class, audited state (see `audit/audit_log.py`), not a
silent fallback.

---

## 1. Taxonomy A — Task type

Maps to the existing `RequestType` enum in `policy/schemas.py`. Kept deliberately small
and stable — this is the coarse label carried through the whole pipeline, not where the
detail lives.

```
LOOKUP           — retrieve a known fact or previously computed answer
COMPUTATION      — produce a value via a defined procedure
CLASSIFICATION   — assign a category/label
GENERATION       — produce new content (text, code, structured artifact)
JUDGMENT         — compare, rank, decide, or recommend among options
HIGH_STAKES      — anything crossing a policy/risk threshold, regardless of the above
UNKNOWN          — classifier confidence too low to assign a category
```

No changes proposed to this enum. Taxonomy B below is what determines *which solver
inside a tier* handles a given `RequestType`.

---

## 2. Taxonomy B — Computational structure catalogue

This is the detailed catalogue. Each entry lists: the underlying computational
structure, representative user phrasings, the conventional solver family, and which
existing tier module should own it. **Nothing here adds a new tier** — every row routes
into one of the five tiers that already exist (`cache_lookup`, `deterministic`,
`small_classifier`, `rag_small_model`, `llm_call`).

### 2.1 Retrieval

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Exact key-value lookup | "capital of France", "HTTP 404 meaning" | hash map / static dict | `tiers/deterministic.py` |
| Cached prior answer | repeated normalized query | exact-match cache | `tiers/cache_lookup.py` |
| Indexed / full-text search | "find files containing X" | inverted index | `tiers/deterministic.py` |
| Structured DB query | "customers where region = X" | SQL execution | `tiers/deterministic.py` (translator may use `small_classifier` for NL→SQL, execution stays deterministic) |
| Semantic retrieval | "find the passage about Y" | embeddings + vector search | `tiers/rag_small_model.py` |

### 2.2 Computation (arithmetic, financial, date, unit, symbolic)

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Basic arithmetic | "17% of 4,850" | calculator | `tiers/deterministic.py` |
| Financial arithmetic | EMI, compound interest, amortization | finance library | `tiers/deterministic.py` |
| Date/time arithmetic | age, business days, deadlines | calendar library | `tiers/deterministic.py` |
| Unit conversion | length, mass, temperature | unit-conversion table | `tiers/deterministic.py` |
| Symbolic math | solve/factor/differentiate/integrate | symbolic algebra engine (e.g. SymPy) | `tiers/deterministic.py` |
| Numerical computation | root-finding, matrix ops, interpolation | numerical library (e.g. NumPy/SciPy) | `tiers/deterministic.py` |

### 2.3 Statistics & probability

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Descriptive stats | mean/median/stdev/percentiles | stats library | `tiers/deterministic.py` |
| Dataset aggregation | group-by, rolling averages | dataframe engine | `tiers/deterministic.py` |
| Statistical tests | t-test, chi-square, regression | stats library | `tiers/deterministic.py` |
| Probabilistic inference | Bayesian updating, belief propagation | probabilistic-graphical-model library | `tiers/small_classifier.py` (if modeled) or `tiers/deterministic.py` (closed-form) |
| Analytical probability | "P(at least two sixes in 4 rolls)" | closed-form probability | `tiers/deterministic.py` |
| Monte Carlo simulation | "simulate 1M coin flips" | simulation engine | `tiers/deterministic.py` |

### 2.4 String & pattern operations

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Exact string manipulation | case, trim, split, join | string library | `tiers/deterministic.py` |
| Pattern extraction | emails, phone numbers, dates in text | regex | `tiers/deterministic.py` |
| Fuzzy comparison | edit distance, similarity | string-distance algorithm | `tiers/deterministic.py` |
| Normalization | Unicode/whitespace/punctuation normalization | normalizer | `tiers/deterministic.py` |

### 2.5 Structured-data manipulation

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Sort / filter / dedupe | "sort these 500 names" | standard algorithms | `tiers/deterministic.py` |
| Join / aggregate / pivot | spreadsheet-style operations | dataframe engine | `tiers/deterministic.py` |
| Format conversion | JSON↔CSV↔YAML↔XML | serializer/deserializer | `tiers/deterministic.py` |
| Parsing | code, config, log, protocol parsing | parser / AST builder | `tiers/deterministic.py` |

### 2.6 Validation

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Syntax validation | "is this JSON valid" | format validator | `tiers/deterministic.py` |
| Schema validation | "does this conform to schema X" | JSON Schema / XSD validator | `tiers/deterministic.py` |
| Constraint validation | "age >= 18 and date_end >= date_start" | rule evaluator | `tiers/deterministic.py` |
| Checksum / integrity | ISBN, credit-card, UUID format | checksum algorithm | `tiers/deterministic.py` |

### 2.7 Search, graph, and optimization algorithms

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Shortest path / reachability | "fastest route between A and B" | graph algorithm (Dijkstra/A*) | `tiers/deterministic.py` |
| Topological sort / dependency resolution | "what must happen first" | DAG algorithm | `tiers/deterministic.py` |
| Constraint satisfaction | scheduling, timetabling, packing | CP/SAT/MILP solver | `tiers/deterministic.py` (NL→constraints may use `small_classifier.py`, solving stays deterministic) |
| Combinatorial / linear optimization | routing, allocation, scheduling | LP/MILP/heuristic solver | `tiers/deterministic.py` |

### 2.8 Extraction & classification (rule-based to semantic)

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Rule-based extraction | invoice numbers matching a pattern | regex/template | `tiers/deterministic.py` |
| Structured-field extraction | forms with known field layout | template parser | `tiers/deterministic.py` |
| Rule/lookup classification | "HTTP 404 → client_error" | lookup table / rule | `tiers/deterministic.py` |
| Statistical classification | spam, sentiment, language ID | classical ML model | `tiers/small_classifier.py` |
| Semantic classification | ambiguous category, needs interpretation | small language model | `tiers/small_classifier.py` |
| Open-ended classification | categories themselves are unclear | full LLM | `tiers/llm_call.py` |

### 2.9 Ranking

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Deterministic ranking | sort by price/date/score | comparator | `tiers/deterministic.py` |
| Relevance ranking | BM25 / retrieval scoring | IR ranking function | `tiers/rag_small_model.py` |
| Weighted multi-criteria scoring | explicit weighted criteria given | scoring function | `tiers/deterministic.py` (criteria extraction may use `small_classifier.py` if criteria are stated in free text) |

### 2.10 Diagnosis, prediction, forecasting

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Rule-based diagnosis | decision-tree fault finding | decision tree / expert rules | `tiers/deterministic.py` |
| Time-series forecasting | trend/seasonal forecasting | ARIMA/ETS or specialized model | `tiers/small_classifier.py` |
| Anomaly detection | "find the unusual months" | statistical/ML anomaly detector | `tiers/small_classifier.py` |
| Causal inference | "did X cause Y" | causal-inference method (not LLM improvisation) | `tiers/small_classifier.py` if a model exists; otherwise escalate with explicit low-confidence flag, do not let `llm_call.py` assert causal claims ungrounded |

### 2.11 Perception (non-text modalities)

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Image transforms | resize/crop/rotate/format convert | image library | `tiers/deterministic.py` |
| OCR (clean scans) | printed text extraction | OCR engine | `tiers/small_classifier.py` |
| Audio transforms | trim/normalize/convert | audio library | `tiers/deterministic.py` |
| Speech-to-text / TTS | transcription, synthesis | specialized speech model | `tiers/small_classifier.py` |

> Note: `triage/modality_router.py` (Stage 3, already named in `ARCHITECTURE.md`) is
> the correct place to dispatch by modality before this table applies within a
> modality — this document does not change that.

### 2.12 Template-based / deterministic generation

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Templated documents | invoices, receipts, certificates | template engine + variables | `tiers/deterministic.py` |
| Deterministic code/config generation | JSON payload, SQL INSERT, Dockerfile from known schema | template engine | `tiers/deterministic.py` |
| Code execution (not simulation) | "what does this code output" | sandboxed execution | `tiers/deterministic.py` |

### 2.13 Grounded synthesis (genuinely needs retrieval + language)

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Document QA over provided material | "what does this paper say about X" | retrieval + small model | `tiers/rag_small_model.py` |
| Multi-document synthesis (bounded) | "summarize agreement across these 5 sources" | retrieval + small model | `tiers/rag_small_model.py` |

### 2.14 Open-ended reasoning / generation (genuine LLM territory)

| Subcategory | Example | Solver | Owning module |
|---|---|---|---|
| Ambiguous, under-specified requests | "help me decide which laptop is right for me" | full LLM | `tiers/llm_call.py` |
| Open-ended creative generation | stories, marketing copy, brainstorming | full LLM | `tiers/llm_call.py` |
| Stylistic/semantic rewriting | "make this sound empathetic, not patronizing" | full LLM | `tiers/llm_call.py` |
| Multi-step reasoning without a formal solver | genuinely ambiguous causal/ethical reasoning | full LLM (high reasoning) | `tiers/llm_call.py` |

### 2.15 `UNKNOWN` — explicit, audited, non-default

Any request `triage/classifier.py` cannot map to a row above with sufficient confidence
must be tagged `computational_structure = UNKNOWN` and still proceed through the normal
cheapest-first ladder from Stage 3 (cache → deterministic → small classifier → RAG →
LLM), exactly as `ARCHITECTURE.md` already specifies, with the `UNKNOWN` tag itself
logged per Stage 3's audit requirement ("full rationale for the selected tier, including
which cheaper tiers were tried and rejected and why"). This is what prevents
"we don't recognize this category" from silently meaning "send to the LLM."

---

## 3. Taxonomy C — Required capability

A thinner, capability-oriented cut across the same catalogue, useful for
`triage/decision.py`'s scoring inputs and for `cost/model_registry.py` when multiple
models could serve the same tier:

```
exact_retrieval            structured_extraction        planning_bounded
semantic_retrieval         entity_extraction            control (future work)
arithmetic                 rule_evaluation               perception_visual
symbolic_manipulation      constraint_solving            perception_audio
numerical_computation      graph_algorithms              language_understanding
statistical_inference      optimization                  open_ended_generation
probabilistic_inference    ranking_scoring                tool_use / API call
causal_inference           classification_statistical    environment_action
format_transformation      classification_semantic
```

`triage/decision.py` should treat this list as the vocabulary a `RequestClassification`
can be tagged with (in addition to `RequestType`), not as a new pipeline stage.

## 4. Taxonomy D — Execution mechanism (unchanged tier ladder)

No new tiers. Restated here only to make explicit that everything above resolves to one
of the tiers `ARCHITECTURE.md` Stage 3 already defines:

```
cache_lookup            (Tier: CACHE)
deterministic           (Tier: DETERMINISTIC)   ← absorbs the large majority of
                                                    Taxonomy B categories 2.1–2.12
small_classifier        (Tier: SMALL_CLASSIFIER) ← absorbs classical/specialized ML
rag_small_model         (Tier: RAG_SMALL_MODEL)  ← absorbs grounded/retrieval synthesis
llm_call (low/high)     (Tier: LLM_*)            ← genuinely open-ended cases only
```

`tiers/deterministic.py` in particular should be expected to internally dispatch across
many solver families (arithmetic, string ops, parsers, validators, graph/optimization
algorithms, template generation, sandboxed execution) rather than being a single
function — that internal dispatch is implementation detail within one stub, consistent
with `CONSTITUTION.md`'s rule that filling in stubs with real logic isn't a structural
change.

---

## 5. Cross-cutting principle for `triage/classifier.py`

For every request, resolution should attempt, in order, before falling to the next:

1. Is the answer already cached? → `CACHE`
2. Does a deterministic algorithm/solver exist for this exact computational structure? → `DETERMINISTIC`
3. Does a classical/specialized ML model exist for this? → `SMALL_CLASSIFIER`
4. Does it require grounded retrieval + light synthesis? → `RAG_SMALL_MODEL`
5. Does it require genuinely open-ended reasoning/generation? → `LLM_LOW_REASONING` / `LLM_HIGH_REASONING`
6. None of the above matched confidently → tag `UNKNOWN`, still walk the ladder from step 1, log the `UNKNOWN` tag per Stage 3's audit requirement.

This is the same escalation order `ARCHITECTURE.md` Stage 3 already specifies — this
document only adds the granularity for step 2–4 recognition.

---

## 6. Explicit non-goal: this catalogue is not claimed to be exhaustive

No fixed list of categories can be proven to cover every future user prompt. Per
`RESEARCH_TRACEABILITY.md`'s standard, the defensible claim is architectural, not
enumerative:

> The runtime uses a compositional, extensible category catalogue (this document) and
> a stub-per-tier solver structure, so that a request without a matching registered
> category is tagged `UNKNOWN` and still routed through the cheapest-first ladder,
> rather than silently defaulting to the LLM tier.

New rows can be added to §2 at any time as new request patterns are observed in the
golden test set (Sprint 2+) or in `guardrails/adversarial/router_attack_suite.py`
findings — this is expected content growth to a reference document, not a change to
`ARCHITECTURE.md`, and does not require a Change Proposal.

## 7. Explicitly out of scope here (tracked separately)

- **Request decomposition** (splitting one compound request into subproblems executed
  by different tiers) — deferred as future work by explicit project-owner decision.
  Should it later be reconsidered, it requires a Change Proposal under
  `CONSTITUTION.md`, since it changes Stage 3's inputs/outputs and Stage 5's execution
  model.
- **Environment action / tool orchestration as a first-class task type** (e.g. "book
  this flight," "send this email") — currently falls under `GENERATION`/`JUDGMENT` in
  Taxonomy A by default; a dedicated `ACTION` request type is a candidate for a future,
  separately-proposed change, not addressed here.

## 8. Traceability

This document elaborates `triage/taxonomy.py`, `triage/classifier.py`, and the internal
solver logic of `tiers/*.py`, all already listed in `RESEARCH_TRACEABILITY.md`. It adds
no new component and traces to the same entries already cited there — principally the
LLM-agents review's "is this too simple to decompose" gap, the Practices/Norms in
Education paper's observed human heuristics for task routing, and the NIST AI RMF
Manage-function principle that whether AI is the appropriate solution should itself be
assessed rather than assumed.
