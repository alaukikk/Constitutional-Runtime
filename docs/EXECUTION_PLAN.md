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

**Important integration boundary:** `triage/classifier.py` exists and is tested, but the current `api/main.py` live tier ladder does **not** call it yet. Full classifier-driven graduated routing remains scheduled for Sprint 4.

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

The Sprint 3 implementation is now committed to the GitHub `main` repository, including the session-state, cost-estimator, model-selector, tests, and `api/main.py` integration work. The repository snapshot was reviewed after the final integration update.

**Sprint 3 is therefore closed as an implementation sprint.** Remaining limitations and calibration work are tracked in `OPEN_ENDS.md`; they are not silently treated as completed.

### Deliberate Sprint 3 limitations carried forward

- Session IDs are still caller-supplied/anonymous at this layer. A caller that rotates IDs can bypass accumulated session context; server-issued or signed IDs require an upstream authentication/session boundary and remain open as `OI-013`.
- The live Stage 2 gate records the current turn with `turn_cost=0.0` because the final execution cost is not known before the gate. This means cumulative-cost thresholding is intentionally approximate until a pre-execution estimate is threaded into the gate; the actual estimator output remains available to the execution/audit path.
- Session thresholds remain placeholders and require calibration against the golden set and empirical cost data (`OI-018`).
- Energy anchors/model-catalog values are not yet fully empirical; assumptions and provenance remain explicit in the estimator/model registry (`OI-005`, `OI-017`).

---

## Sprint 4 — Feedforward + graduated tier ladder (NEXT)

- `interface/feedforward.py` (Stage 4) — hard gate before high-cost/high-stakes execution.
- `triage/decision.py` expanded into the full graduated ladder (cache → deterministic → small classifier → RAG → LLM low/high reasoning).
- `tiers/small_classifier.py`, `tiers/rag_small_model.py` → real implementations.
- Integrate the classifier into the live request path; this was intentionally deferred from Sprint 2 rather than retroactively claiming it was live.
- Resolve the Stage 1 `REQUIRE_HUMAN` path with the human-checkpoint interface where required by the frozen architecture.

**Verification:** confirm every routing decision in the audit log carries the intended cost estimate; run the planned feedforward scrutiny pilot as an implementation-stage study, not the full capstone experiment.

---

## Sprint 5 — Escalation, validation, governance

- `escalation/repair_router.py` (cross-cutting) — real stage-to-stage escalation, not just a post-validation loop.
- `validation/validator.py`, `validation/non_llm_checks.py` (Stage 6) — with the "validator is not privileged" rule enforced (if LLM-based, logged/costed identically to primary calls).
- `policy/governance/change_log.py`, `CODEOWNERS` — enforced on `constitution.yaml` PRs.
- `triage/bias_monitor.py` — first real routing-outcome comparison across phrasing/language.

**Test:** deliberately inject a failure at each stage (bad policy match, failed validation, execution error) and confirm the correct repair/escalation path fires for each.

---

## Sprint 6 — Modality awareness, hardened adversarial testing

- `triage/modality_router.py` — even a minimal "non-text input gets limited/flagged support" is sufficient for this sprint.
- `guardrails/adversarial/router_attack_suite.py`, `classifier_attack_suite.py` — run against the *whole* pipeline, not just Stage 0 in isolation.
- Full audit schema implemented, replacing the Sprint 1 partial version.

**Test:** adversarial suite catches known jailbreak/injection payloads; confirm the router/classifier themselves resist the misclassification attacks identified in architecture review.

---

## Sprints 7–8 — The actual experiment

This is where the capstone's central claims get tested, using the
evaluation framework in `RESEARCH_TRACEABILITY.md`.

1. **Build the golden test set** properly — the working set accumulated informally across Sprints 2–6, cleaned up and expanded.
2. **Run `cost/breakeven.py` for real** against accumulated usage data — answer the central research question: at what workload characteristics does the runtime produce net savings after its own overhead?
3. **Full-team red-team session** — adversarial inputs against the whole pipeline; sanity-check cost numbers; confirm escalation fires correctly under real (not synthetic) conditions.
4. **Comparative evaluation** — constitutional runtime vs. "always call the LLM directly" baseline, across all five evaluation dimensions (resource efficiency, decision quality, constitutional compliance, human agency, runtime overhead).
5. **Shadow-mode validation** — log what the runtime *would* have chosen on real traffic without acting on it, before treating it as load-bearing.

**This is the deliverable that proves the thesis**, not just "the code runs."

---

## Open items

The authoritative unresolved-work register is `OPEN_ENDS.md`. Do not maintain a second
list here; update the register when new gaps are discovered or old ones are resolved.
