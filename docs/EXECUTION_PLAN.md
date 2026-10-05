# Execution Plan

Maps `ARCHITECTURE.md` → modules → sprint → tests → experiments →
capstone evaluation. This is the living tracker; `ARCHITECTURE.md`
itself stays frozen while this document's status updates sprint by sprint.

**Documentation precedence:** stage structure/interfaces/security boundaries belong to
`ARCHITECTURE.md`; sprint/completion status belongs here; known gaps belong to
`OPEN_ENDS.md`; research mapping belongs to `RESEARCH_TRACEABILITY.md`.

---

## Sprint 1 — Skeleton (COMPLETE)

**Goal:** prove the pipeline runs end-to-end. Not intelligence — plumbing.

| Module | Stage | Status |
|---|---|---|
| `policy/schemas.py` | Shared contract (all stages) | ✅ Done |
| `guardrails/injection_screen.py` | Stage 0 | ✅ Done (basic regex) |
| `policy/engine.py`, `config/constitution.yaml`, `config/failure_modes.yaml` | Stage 1 | ✅ Done (keyword-based) |
| `tiers/*.py` | Stage 3/5 | ✅ Done (stubs — all return `None` except LLM tier, which fakes a response) |
| `cost/model_registry.py` | Stage 3 (data only) | ✅ Done (placeholder catalog) |
| `audit/audit_log.py` | Stage 7 (partial schema) | ✅ Done (subset of full schema) |
| `api/main.py` | Wiring | ✅ Done (security checkpoint was initially a placeholder; Sprint 2 wiring now runs Stage 0/1 before the tier ladder) |

**Historical verification:** a live request was sent through the running FastAPI server and correctly fell through cache → deterministic → LLM stub, with the decision written to the audit log.

**Deliberately not built:** Stage 2 (session), Stage 4 (feedforward), Stage 6 (validator), real Stage 3 classification/scoring, `escalation/repair_router.py`, `triage/bias_monitor.py`, `triage/modality_router.py`, `cost/breakeven.py`, `policy/governance/`.

---

## Sprint 2 — First real tiers (COMPLETE)

Per the architecture review, Sprint 2 was deliberately scoped to proving that the
constitutional decision loop can discriminate between requests, rather than filling
every stub indiscriminately.

**Completed:**
- `tiers/cache_lookup.py` → real Redis-backed exact-match cache. SHA-256 keys over normalized text; Redis failure degrades to a miss.
- `tiers/deterministic.py` → real conservative deterministic solver slice. Arithmetic uses strict parsing and never `eval()`; static facts are supported; ambiguous/multi-operation/divide-by-zero cases fall through.
- `triage/taxonomy.py` + `triage/classifier.py` → first-pass keyword classification. Cheap-tier eligibility is intentionally conservative; `CATEGORY_PRIORITY` prevents keyword dilution and `HIGH_STAKES` wins the tie-break.
- `api/main.py` → Stage 0 → Stage 1 → cheapest-first tier ladder → audit wiring, including cache population after non-cache answers.
- `api/settings.py` → application settings with test-safe defaults and fail-loud validation for invalid configuration.
- `guardrails/output_filter.py` → cheap rule-based output leak detector built, but deliberately not wired into the live path until Stage 6 validation exists.
- `guardrails/adversarial/classifier_attack_suite.py` and `router_attack_suite.py` → adversarial payload suites added; current payloads are exercised against the real Stage 0 gate because the classifier/router are not yet fully integrated into the live path.
- Test layout was restructured into per-module folders and `pytest.ini` was added so the adversarial suites are collected.
- Integration defects found during the real local run were fixed: invalid `requirements.txt` comments, cwd-dependent policy config loading, cache test dependence on ambient Redis, and the classifier's keyword-dilution vulnerability.

**Verification:** the final local Sprint 2 run reported **113 tests passed, 0 failures in 1.50 seconds** after fixing defects exposed by the initial run.

**Important integration boundary:** `triage/classifier.py` exists and is tested, but the current `api/main.py` live tier ladder does **not** call it yet. Full classifier-driven graduated routing remains scheduled for Sprint 4. **This boundary is resolved by the Sprint 4 planner integration described below.**

**Still deliberately deferred:** Stage 4 (feedforward), Stage 6 (validator), real graduated routing, repair routing, governance, bias monitoring, modality routing, multi-provider LLM integration, and the Sprint 3 session/cost/model-selection slice that is now completed below.

---

## Sprint 3 — Session context + real cost accounting (COMPLETE)

**Goal:** close the multi-turn blindness gap and replace placeholder cost handling with an explicit cost-estimation/model-selection layer before expanding the classifier/routing surface.

### Completed scope

- `session/session_state.py` — cumulative risk, cumulative cost, turn count, monotonic session constraints, immutable snapshots, and concurrency-safe in-memory session storage. Session context may only tighten Stage 1 decisions.
- `cost/estimator.py` — per-tier/model estimates for energy, dollars, latency, token usage, runtime overhead, and uncertainty ranges; assumptions are kept explicit where empirical anchors are not yet available.
- `tiers/model_selector.py` — model selection across candidate models using capability floors and an explicit energy or dollar objective, with conservative escalation when no candidate satisfies the floor and auditable alternatives.
- `api/main.py` — Stage 2 is now in the live request path after Stage 0/1 and before Stage 3/5. Each request is recorded once; Stage 0 blocks are recorded before returning; session constraints can tighten the Stage 1 action; session snapshots and Stage 0 results are carried into the audit record.
- Audit rollout — Sprint 3 fields `stage0_screen_result` and `session_state_snapshot` are now passed through the live audit path. The cost estimator/model-selection data is available to the routing layer; the remaining full audit-schema rollout continues in later sprints.
- Sprint 3 tests include the model-selector suite covering capability floors, conservative escalation, objective selection, validation, determinism, and immutable alternatives. Session-state tests cover cumulative risk/cost, monotonic constraints, malformed inputs, concurrency, and snapshot safety.

### Verification / closure

The Sprint 3 implementation is committed to the GitHub `main` repository, including the session-state, cost-estimator, model-selector, tests, and `api/main.py` integration work. The repository snapshot was reviewed after the final integration update.

**Sprint 3 is therefore closed as an implementation sprint.** Remaining limitations and calibration work are tracked in `OPEN_ENDS.md`; they are not silently treated as completed.

### Deliberate Sprint 3 limitations carried forward

- Session IDs are still caller-supplied/anonymous at this layer. A caller that rotates IDs can bypass accumulated session context; server-issued or signed IDs require an upstream authentication/session boundary and remain open as `OI-013`. The same identity/session boundary also applies to the human-confirmation token.
- The live Stage 2 gate records the current turn with `turn_cost=0.0` because the final execution cost is not known before the gate. This means cumulative-cost thresholding is intentionally approximate until a pre-execution estimate is threaded into the gate; the actual estimator output remains available to the execution/audit path. Plan estimates now exist after Stage 2, so threading a pre-execution cost into the session gate is feasible (`OI-036`).
- Session thresholds remain placeholders and require calibration against the golden set and empirical cost data (`OI-018`).
- Energy anchors/model-catalog values are not yet fully empirical; assumptions and provenance remain explicit in the estimator/model registry (`OI-005`, `OI-017`).

---

## Sprint 4 — Graduated routing + feedforward (Implementation complete; carry-forwards tracked in OPEN_ENDS)

**Goal:** replace the current hardcoded tier loop with an auditable planning layer that evaluates the graduated ladder, while adding the Stage 4 feedforward/human-checkpoint boundary.

### Current Sprint 4 work

The committed Sprint 4 planner, live-path integration, confirm-before-execute checkpoint, feedforward route/outcome text, and high-cost confirmation gate are now repository state. The API walks the plan rather than the old hardcoded tier ladder. `REQUIRE_HUMAN` is an actual confirm-before-execute gate rather than a placeholder/unavailable path.

`plan_request(text)` is a pure planning step: it does not execute a tier. It produces the complete candidate ladder, an attempt/skip decision for each rung, reasons for skips, and cost estimates. `api/main.py` walks `plan.attempt_order`; once a tier answers, `plan.decision_for(tier, flags)` produces the auditable `RoutingDecision` rather than having `main.py` reconstruct the decision manually.

The human checkpoint uses a signed, single-use confirmation token bound to the session, exact normalized text, and triggering rule set. The first `REQUIRE_HUMAN` call withholds execution and returns a confirmation token; a confirming call must submit that token with the same request. The token never overrides a BLOCK. Its remaining identity limitation and per-process state are tracked in `OPEN_ENDS.md` (`OI-013`, `OI-040`, `OI-041`).

### Implemented Sprint 4 planner decisions

1. **Confidence is an escalate-only floor.** Category eligibility remains the primary gate. Low confidence may remove the small-classifier and RAG rungs, but must never force a cheaper or less capable route. The default floor is `0.4`; the current classifier confidence formula bottoms out at `0.55`, so calibration remains open (`OI-029`, `OI-052`).
2. **The deterministic rung is not classifier-gated.** The deterministic solver remains independently eligible and can answer inputs such as `2 + 2` even when the classifier labels the request `UNKNOWN`. It is skipped for `HIGH_STAKES` requests, while its own solver remains self-gating and returns `None` when unsure.
3. **Classifier failure escalates conservatively.** A classifier exception or invalid return is treated as `UNKNOWN` with confidence `0.0`, cheap classifier/RAG rungs are skipped, and the LLM rung uses the maximum-capability escalation path rather than silently taking a weaker model.
4. **`LLM_HIGH_REASONING` remains outside the normal Sprint 4 ladder.** It is reserved for explicit repair/escalation in Sprint 5 (`OI-034`).
5. **High-stakes LLM routing carries a capability floor of `0.7` in the current planner.** The underlying catalog capability scores remain placeholders and are tracked by `OI-005`/`OI-033`.

### Planner implementation and test coverage

`triage/decision.py` contains `TierStep`, `RoutingPlan`, `attempt_order`, auditable `rationale`, and `decision_for(...)`. The planner tests cover attempt order, high-stakes capability floor, cache-first/LLM-last invariant, unknown-category behavior, confidence-floor monotonicity and validation, classifier failure, per-step reasons/estimates, audit rationale, and deterministic planning. The development history reports **36 passing tests** for this planner suite and **7 API integration tests**; these remain reported development-session results.

### Human checkpoint implementation

`interface/human_checkpoint.py` provides the confirm-before-execute gate for `REQUIRE_HUMAN`. Tokens are HMAC-SHA256 signed, bound to session/exact normalized text/rule IDs, time-limited, and single-use with atomic verification/consumption. Verification fails closed on internal errors. `api/main.py` exposes `needs_confirmation` and `confirmation_token` in the response model.

The current checkpoint deliberately proves an explicit, content-bound second call rather than human identity. First-class audit fields for checkpoint-triggered/confirmed state remain `OI-042`, while once-only risk charging remains a decision item (`OI-043`).

### Feedforward implementation

`interface/feedforward.py` is committed and integrated as Stage 4. It provides templated route-preview/outcome text from the pure `RoutingPlan` and a high-cost confirm gate based on worst-case energy/cost estimates. The gate uses `3 Wh` and `$0.05` placeholder limits. For gated requests, the route preview is included before execution; for ungated requests, outcome text is attached to the response because the current single-call API has no separate pre-generation preview mode.

Rendering failures currently fail open so execution can continue without feedforward text; cost-gate evaluation failures fail closed and require confirmation. These are explicit implementation interpretations rather than frozen constitutional requirements; `OI-050` remains open pending a policy decision. Remaining feedforward/user-study gaps are tracked in `OPEN_ENDS.md` (`OI-045`–`OI-050`, `OI-059`).

### Small classifier implementation

`tiers/small_classifier.py` is now implemented as a lightweight TF-IDF + logistic-regression classifier using `scikit-learn`, with abstention when confidence is below its configured floor. Its current seed is deliberately synthetic, hand-written, and English-only (`tiers/spam_seed_synthetic.py`). The seed is for implementation/unit testing only and is not evaluation evidence; a separate held-out evaluation set must be independently constructed and frozen before threshold tuning (`OI-051`, `OI-052`, `OI-057`). The classifier remains outside `CLASSIFICATION`-eligible live routing until the existing policy decision in `OI-031` is resolved (`OI-053`).

### Retrieval / RAG boundary

`tiers/retrieval.py` now provides the retrieval half of the intended grounded-answer path, with `audit/metrics.py` providing retrieval evaluation helpers. The file explicitly distinguishes retrieval from the RAG tier: `tiers/rag_small_model.py` still does not perform the small-model generation step. Retrieval-only functionality therefore must not be described as completed RAG (`OI-054`). The existing estimator observation that RAG can cost more than a same-model plain LLM because of retrieval/context overhead remains tracked by `OI-030`.

### Sprint 4 findings requiring explicit tracking

- `CLASSIFICATION` is currently excluded from `CHEAP_TIER_ELIGIBLE`; this remains a routing-policy decision (`OI-031`, `OI-053`).
- The estimator contains placeholder runtime/cost inputs; lightweight-tier energy/cost figures are therefore developmental estimates until measured workloads are available (`OI-005`, `OI-055`).
- The live Stage 2 gate records the current turn with `turn_cost=0.0`; cumulative-cost thresholding remains approximate until a pre-execution estimate is threaded into the gate (`OI-036`).
- The planner intentionally does not duplicate `SessionState` enforcement; `api/main.py` remains responsible for combining the session floor with the Stage 1 action before routing (`OI-037`).
- The high-cost feedforward limits remain placeholders and require calibration alongside the model/cost catalog before they support empirical claims (`OI-045`).

- **OI-058 resolved:** audit records now distinguish `executed`, `withheld_pending_confirmation`, and `blocked`; withheld-route estimates are stored separately from zero placeholder execution cost. The Sprint 5 `executed_withheld` audit state is additionally recorded through OI-071, as tracked in `OPEN_ENDS.md`.

### Remaining Sprint 4 sequence

1. Resolve the `CLASSIFICATION` eligibility question before enabling the small-classifier rung for those requests (`OI-031`, `OI-053`).
2. Construct and freeze an independent classifier evaluation set, then calibrate the confidence threshold without using the synthetic seed as evaluation evidence (`OI-052`, `OI-057`).
3. Complete the `rag_small_model.py` generation boundary only after the grounding corpus/model decision is explicit (`OI-054`).
4. Carry forward the empirical resource, fairness, human-agency, and cost-accounting work into the appropriate later evaluation sprint (`OI-055`–`OI-059`).

**Verification status:** the planner, API integration, human-checkpoint implementation, feedforward implementation, small-classifier implementation, synthetic seed, retrieval prototype, and associated tests are committed on `main`. The latest full-suite run reports **414 tests passed, 1 skipped (local run, Windows, Python 3.11.7)**. The skipped test is the Windows symlink test. Sprint 4 automated test verification is complete; carry-forwards remain tracked in `OPEN_ENDS.md`.
## Sprint 5 — Escalation, validation, governance (IN PROGRESS)

### Implemented

- `validation/non_llm_checks.py` — cheap rule-based output checks: non-empty output, size/control-character checks, and the existing output safety-leakage filter.
- `validation/validator.py` — Stage 6 validator using the non-LLM checks. Validator-level errors follow the existing `failure_modes.yaml` policy semantics; the implementation does not consult the classifier's `HIGH_STAKES` category when deciding fail-open/fail-closed behavior.
- `escalation/repair_router.py` — cross-cutting repair decision module. It supports validation failures and execution errors, escalates strictly upward, permits at most one escalation, checks cumulative worst-case estimates against the existing high-cost limits, and withholds when repair is unavailable or unsafe.
- `api/main.py` — live Stage 6 validation/repair wiring after execution, with repair routing on validation failure or execution error; covered by `tests/api/test_main_validation_wiring.py`.
- `audit/audit_log.py` — `executed_withheld` execution state and `validation_trace` for validation/repair/withholding outcomes.
- Cache semantics — cache writes occur only after validation, and cache hits are validated before release.
- Feedforward outcome disclosure — later repair escalation is disclosed in the response outcome text.
- `tests/escalation/test_repair_router.py` — coverage for target selection, the one-escalation bound, cumulative cost ceiling, cap-check failures, safety-leakage/non-retry cases, validator errors, malformed inputs, and withholding semantics.

### Remaining Sprint 5 work

- `policy/governance/change_log.py` and `policy/governance/CODEOWNERS` are present but currently empty; governance enforcement is therefore not implemented yet.
- `triage/bias_monitor.py` is present but currently empty; the first routing-outcome comparison across phrasing/language remains to be implemented.
- Repair-router N1 remains a provisional implementation judgment tracked under `OI-065`; the terminal `WITHHOLD` behavior is resolved under `OI-066` and remains outside the frozen architecture.

**Verification boundary:** validator, repair-router, and live API validation/repair-wiring tests are committed on `main`. Sprint 5 is still not complete and no end-to-end Sprint 5 completion claim is made because governance enforcement and the bias monitor remain unimplemented. The owner-reported local full-suite result is tracked in `README.md`; it is not an independent verification claim.

**Test target:** deliberately inject a validation failure and a Stage 5 execution error through the live pipeline and confirm the correct repair/escalation/withhold path fires for each, while preserving the frozen Stage 0→7 ordering. This is covered by `tests/api/test_main_validation_wiring.py`.

## Sprint 6 — Modality awareness, hardened adversarial testing

- `triage/modality_router.py` — even a minimal "non-text input gets limited/flagged support" is sufficient for this sprint.
- `guardrails/adversarial/router_attack_suite.py`, `classifier_attack_suite.py` — run against the *whole* pipeline, not just Stage 0 in isolation.
- Full audit schema implemented, replacing the Sprint 1 partial version.

**Test:** adversarial suite catches known jailbreak/injection payloads; confirm the router/classifier themselves resist the misclassification attacks identified in architecture review.

## Sprints 7–8 — The actual experiment

This is where the capstone's central claims get tested, using the evaluation framework in `RESEARCH_TRACEABILITY.md`.

1. **Build the golden test set** properly — the working set accumulated informally across Sprints 2–6, cleaned up and expanded.
2. **Run `cost/breakeven.py` for real** against accumulated usage data — answer the central research question: at what workload characteristics does the runtime produce net savings after its own overhead?
3. **Full-team red-team session** — adversarial inputs against the whole pipeline; sanity-check cost numbers; confirm escalation fires correctly under real (not synthetic) conditions.
4. **Comparative evaluation** — constitutional runtime vs. "always call the LLM directly" baseline, across all five evaluation dimensions (resource efficiency, decision quality, constitutional compliance, human agency, runtime overhead).
5. **Shadow-mode validation** — log what the runtime *would* have chosen on real traffic without acting on it, before treating it as load-bearing.

**This is the deliverable that proves the thesis**, not just "the code runs."

## Open items

The authoritative unresolved-work register is `OPEN_ENDS.md`. Do not maintain a second list here; update the register when new gaps are discovered or old ones resolved.
