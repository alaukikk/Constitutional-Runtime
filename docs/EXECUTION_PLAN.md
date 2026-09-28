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
| `cost/model_registry.py` | Stage 3 (data only) | ✅ Done (fake placeholder data) |
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

**Important integration boundary:** `triage/classifier.py` exists and is tested, but the current `api/main.py` live tier ladder does **not** call it yet. The live path is still cache → deterministic → small-classifier stub → RAG stub → LLM. Full classifier-driven graduated routing remains scheduled for Sprint 4.

**Still deliberately deferred:** Stage 2 (session), Stage 4 (feedforward), Stage 6 (validator), real cost estimation/model selection, repair routing, governance, bias monitoring, modality routing, and multi-provider LLM integration.

---

## Sprint 3 — Session context + real cost accounting (IN PROGRESS / NOT YET COMMITTED TO `main`)

**Goal:** close the multi-turn blindness gap and replace placeholder cost data with a
real cost model before expanding the classifier/routing surface.

### Planned scope

- `session/session_state.py` — cumulative risk, cumulative cost, turn count, and monotonic constraints; session context may only tighten Stage 0/1 decisions.
- `cost/estimator.py` — real per-tier estimates for energy/dollars/latency.
- `tiers/model_selector.py` — model selection across candidate models based on cost/capability/latency, separate from the call-execution module.
- Wiring pass — connect session state to the live request path and make blocked turns count toward the session state.
- Audit rollout — Sprint 3 adds `stage0_screen_result`, `session_state_snapshot`, and `estimated_cost` to the audit record; later fields roll out in Sprints 4–5, with full-schema verification in Sprint 6.

### History-derived implementation status

The Claude Sprint 3 history reports that `session/session_state.py` was implemented and its
14-test suite passed locally. However, the current GitHub `main` snapshot still has an empty
`session/session_state.py`, `cost/estimator.py`, and `tiers/model_selector.py`. Therefore this
plan records Sprint 3 as **in progress / not yet committed to `main`**, rather than treating
local chat-session work as repository completion. See `OPEN_ENDS.md` OI-001 and OI-026.

### Known Sprint 3 blockers / decisions

- Server-controlled or signed session IDs are needed; client-controlled IDs can otherwise rotate history and defeat Stage 2. (`OPEN_ENDS.md` OI-013)
- Blocked turns must still be recorded before returning. (`OI-014`)
- The mechanism by which the session floor reaches `RoutingDecision` is still a decision point; the current proposal is to carry it as a `PolicyFlag` without changing the shared schema. (`OI-015`)
- Energy is required by the frozen Stage 3/audit specification but is absent from the current cost interfaces. A decision is required before `cost/estimator.py` can be completed. (`OI-017`)
- Session thresholds are placeholders and require calibration against the golden set and real cost data. (`OI-018`)

---

## Sprint 4 — Feedforward + graduated tier ladder

- `interface/feedforward.py` (Stage 4) — hard gate before high-cost/high-stakes execution
- `triage/decision.py` expanded into the full graduated ladder (cache → deterministic → small classifier → RAG → LLM low/high reasoning)
- `tiers/small_classifier.py`, `tiers/rag_small_model.py` → real
- Integrate the classifier into the live request path; this is intentionally deferred from Sprint 2 rather than retroactively claiming it was live.

**Test:** confirm every routing decision in the audit log carries a real cost estimate; small user study on feedforward's effect on scrutiny (informal pilot, not the full capstone experiment yet).

---

## Sprint 5 — Escalation, validation, governance

- `escalation/repair_router.py` (cross-cutting) — real stage-to-stage escalation, not just a post-validation loop
- `validation/validator.py`, `validation/non_llm_checks.py` (Stage 6) — with the "validator is not privileged" rule enforced (if LLM-based, logged/costed identically to primary calls)
- `policy/governance/change_log.py`, `CODEOWNERS` — enforced on `constitution.yaml` PRs
- `triage/bias_monitor.py` — first real routing-outcome comparison across phrasing/language

**Test:** deliberately inject a failure at each stage (bad policy match, failed validation, execution error) and confirm the correct repair/escalation path fires for each.

---

## Sprint 6 — Modality awareness, hardened adversarial testing

- `triage/modality_router.py` — even a minimal "non-text input gets limited/flagged support" is sufficient for this sprint
- `guardrails/adversarial/router_attack_suite.py`, `classifier_attack_suite.py` — run against the *whole* pipeline, not just Stage 0 in isolation
- Full audit schema implemented, replacing the Sprint 1 partial version

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
