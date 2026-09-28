# Execution Plan

Maps `ARCHITECTURE.md` → modules → sprint → tests → experiments →
capstone evaluation. This is the living tracker; `ARCHITECTURE.md`
itself stays frozen while this document's "status" columns update
sprint by sprint.  


Audit schema rollout: audit/audit_log.py grows additively. ARCHITECTURE.md's schema is the target; this plan owns the timing. Sprint 3: stage0_screen_result, session_state_snapshot, estimated_cost. Sprint 4: alternatives_considered, feedforward_shown, user_confirmed, actual_cost. Sprint 5: validation_result, escalations, human_checkpoint_triggered, final_outcome. Sprint 6: verify the full schema is present.

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
| `api/main.py` | Wiring | ✅ Done (security checkpoint marked as placeholder, not yet plugged in) |

**Verified:** live request sent through running FastAPI server, correctly fell through cache → deterministic → LLM stub, decision confirmed written to audit log.

**Deliberately not built:** Stage 2 (session), Stage 4 (feedforward), Stage 6 (validator), real Stage 3 classification/scoring, `escalation/repair_router.py`, `triage/bias_monitor.py`, `triage/modality_router.py`, `cost/breakeven.py`, `policy/governance/`.

---

## Sprint 2 — First real tiers, not "implement every empty file"

Per the architecture review: Sprint 2 should **not** mean filling in
every stub indiscriminately. It should prove the **constitutional
decision loop** actually discriminates between requests, using the
smallest real slice that demonstrates it.

**Scope:**
- `tiers/cache_lookup.py` → real (Redis-backed, exact-match only per the core trust-boundary principle)
- `tiers/deterministic.py` → real (absorbs calculator/rule-based logic)
- `triage/taxonomy.py` + first-pass `triage/classifier.py` → enough to distinguish "cheap tier suffices" vs. "needs AI," not the full reasoning-depth dial yet

**Explicitly deferred to Sprint 3+, per architecture review recommendation:**
- LiteLLM / multiple real providers — infrastructure, not the research contribution yet. Sprint 2's experiment should work with: deterministic execution, one cheap model, one stronger model, simulated/estimated costs, the constitution, a validator, audit logs. That's enough to test the central hypothesis without infrastructure complexity obscuring it.

**Test:** golden set of ~20-30 hand-labeled requests with expected tier assignment; confirm cache/deterministic actually intercept the ones they should, and correctly fall through on the ones they shouldn't.

---

## Sprint 3 — Session context + real cost accounting

- `session/session_state.py`, `session/prefilter.py` (Stage 2) — enforcing "may only tighten, never loosen" from `ARCHITECTURE.md`'s core principle
- `cost/estimator.py` — real per-tier cost estimates (energy/dollar/latency), replacing the Sprint 1 placeholder zeros
- `tiers/model_selector.py` — scoring across multiple candidate models (cost vs. capability vs. latency), separate from `llm_call.py` (which just executes the call)

**Test:** multi-turn scenario where cumulative session risk triggers stricter handling on turn 3, even though turn 3 alone looks harmless in isolation.

---

## Sprint 4 — Feedforward + graduated tier ladder

- `interface/feedforward.py` (Stage 4) — hard gate before high-cost/high-stakes execution
- `triage/decision.py` expanded into the full graduated ladder (cache → deterministic → small classifier → RAG → LLM low/high reasoning)
- `tiers/small_classifier.py`, `tiers/rag_small_model.py` → real

**Test:** confirm every routing decision in the audit log now carries a real cost estimate; small user study on feedforward's effect on scrutiny (informal pilot, not the full capstone experiment yet).

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
- Full audit schema (per `ARCHITECTURE.md` Stage 7) implemented, replacing the Sprint 1 partial version

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

## Open items tracked, not yet scheduled

- Formal user study design for the feedforward/critical-thinking claims (needs its own ethics/methodology pass before Sprint 7).
- Real multi-provider LLM integration (LiteLLM) — infrastructure work, deliberately deprioritized until the core hypothesis is validated with 1–2 models.
- `policy/governance/` full review workflow — currently just folder structure + `CODEOWNERS` intent.
