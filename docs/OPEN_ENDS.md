# Open Items

The single register of anything we said we'd come back to: known gaps,
deferred decisions, cleanups, and things to verify. If it isn't here, it
isn't tracked. `EXECUTION_PLAN.md` points to this file instead of keeping
its own list, so the two can't drift apart.

Adding or resolving an item does **not** need a Change Proposal. If an
item's *resolution* would change a stage's structure, a shared interface
in `policy/schemas.py`, or the runtime constitution, it is marked
**Decision needed** and goes through `CONSTITUTION.md` first (Rules 2 and 4).

Created 2026-09-28, during Sprint 3. Updated after review of the complete Sprint 1–3
Claude history and verification against the current GitHub `main` snapshot.

---

## How to use this file

**Severity**
- **Must-fix** — blocks the Sprint 7–8 red-team/experiment, or makes a claim in the write-up untrue if left open.
- **Should-fix** — real defect or inconsistency; fix when the trigger fires.
- **Nice-to-have** — improvement; drop it if the sprint is tight.
- **Decision needed** — the owner must choose before anyone implements (may require a Change Proposal).

**Status:** Open / In progress / Resolved / Dropped. Never delete a row; resolved and
dropped items stay, with a one-line note, because the history is useful for the capstone write-up.

**Trigger:** the event that means we handle it (not a date).

**Review:** before each sprint closes, go through every item whose trigger has fired.

---

## From Sprint 1 (Skeleton)

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-001 | **Verify repo state vs. plan.** The Sprint 2/Sprint 3 Claude history reports work that was completed and tested locally, but the current GitHub `main` snapshot still has some corresponding files empty (notably `session/session_state.py`, `cost/estimator.py`, and `tiers/model_selector.py`). This is now explicitly a repository-state discrepancy rather than an assumption that the chat history equals a committed implementation. | Must-fix | Before Sprint 3 implementation is treated as complete | Open |
| OI-002 | **Stage 0 screen is basic regex.** The adversarially-tested classifier is a later-sprint, security-owned item. | Should-fix | Sprint 6 (adversarial hardening) | Open |
| OI-003 | **Stage 1 is keyword matching only.** Interface (`list[PolicyFlag]`) is meant to stay stable when matching improves. | Should-fix | Sprint 5–6 | Open |
| OI-004 | **Stage 0 checkpoint was initially an unplugged placeholder.** `api/main.py` now calls the Stage 0 screen before Stage 1/routing, so this specific wiring gap is resolved. | — | — | Resolved (Sprint 2 wiring) |
| OI-005 | **`cost/model_registry.py` holds fake placeholder data** (`stub-small/medium/large`). | Should-fix | While building `cost/estimator.py` | Open |
| OI-006 | **`tiers/llm_call.py` returns a fake response.** Real integration is deferred until the core hypothesis is validated on 1–2 models. | Should-fix | After hypothesis validated on 1–2 models | Open |
| OI-007 | **Audit schema rollout timing was inconsistent across docs.** The timing is now explicitly owned by `EXECUTION_PLAN.md`: Sprint 3 adds `stage0_screen_result`, `session_state_snapshot`, `estimated_cost`; Sprint 4 adds `alternatives_considered`, `feedforward_shown`, `user_confirmed`, `actual_cost`; Sprint 5 adds validation/escalation/human-checkpoint/final-outcome fields; Sprint 6 verifies the complete schema. The implementation itself remains open work, but the documentation conflict is resolved. | — | — | Resolved (timing clarified) |
| OI-008 | **`TBD` fields in `ARCHITECTURE.md`** (cost accounting for Stages 1 and 2, Stage 2 owner) should be filled with measured values or named owners as they become known. No Change Proposal needed. | Nice-to-have | As each is measured | Open |
| OI-009 | **`requirements.txt` was not valid pip format.** Sprint 2 history records that the em-dash descriptions were changed to comments. | — | — | Resolved (Sprint 2 debugging) |

## From Sprint 2 (First real tiers)

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-010 | **LiteLLM / multiple real providers** deliberately deferred. Infrastructure, not the research contribution. | Nice-to-have | After core hypothesis validated with 1–2 models | Open |
| OI-011 | **Golden set of ~20–30 hand-labeled requests** started in Sprint 2 must be carried forward and cleaned up for the real experiment. | Must-fix | Sprint 7 | Open |
| OI-012 | **`EXECUTION_PLAN.md` had no Sprint 2 status.** Sprint 2 is now documented as complete, including the implemented cache/deterministic/classifier slice, API wiring, adversarial work, and the 113-test final run. | — | — | Resolved (docs synchronized) |

## From Sprint 3 (Session context + cost accounting)

Items found while building/reviewing `session/session_state.py` and the Sprint 3 plan.

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-013 | **Session ID rotation.** If clients choose their own session ID, they can restart with a clean history on every request and bypass Stage 2. Fix: server-issued or signed session IDs in `api/main.py`, plus an end-to-end rotation attack test. | Must-fix | Sprint 3 wiring pass; before any red-team | Open |
| OI-014 | **Blocked turns must still be recorded.** `api/main.py` must call `record_turn` before returning on a Stage 0/1 block, since blocked probes are what should accumulate. | Must-fix | Sprint 3 wiring pass | Open |
| OI-015 | **How the session floor reaches `RoutingDecision`.** Current proposal: `triage/decision.py` converts the floor into a `PolicyFlag` (e.g. `rule_id="session.cumulative_risk"`) appended to `policy_flags`, so no schema change. If the owner disagrees, a Change Proposal is needed. | Decision needed | When building `triage/decision.py` | Open |
| OI-016 | **Wire `record_turn` into the request path and run the multi-turn scenario for real** (turn 3 tightens although harmless alone). Bundles OI-004's now-resolved Stage 0 wiring with OI-013 and OI-014 into one Sprint 3 pass. | Must-fix | End of Sprint 3, after estimator/model-selector work | Open |
| OI-017 | **Energy is missing from the cost interfaces.** The frozen Stage 3 specification and audit schema call for energy (`energy_wh`), but the current `TierCostEstimate` only has dollars/latency and `ModelInfo` has no energy field. Adding fields to `policy/schemas.py` changes a shared interface and therefore needs the owner's decision/Change Proposal handling. | Decision needed | Before completing `cost/estimator.py` | Open |
| OI-018 | **Session thresholds are placeholders** (`require_human_risk=4`, `block_risk=12`, `require_human_cost=$1`). Calibrate against golden-set and cost data. | Should-fix | Sprint 7 | Open |
| OI-019 | **No risk decay** (risk is monotonic by design, since decay is a form of loosening). Long benign sessions with a few mild flags will eventually escalate. Revisit only if false escalations show up in testing; changing it may need a Change Proposal. | Decision needed | If golden-set testing shows false escalations | Open |
| OI-020 | **In-memory store is unbounded and the lock is single-process.** Replace with a Redis-backed `SessionStore` with atomic updates. Eviction must not reset a session. | Nice-to-have | Post-capstone, unless the demo needs it | Open |
| OI-021 | **`SessionState`/`SessionConstraints` live in `session_state.py`, not `policy/schemas.py`.** Move only if other modules need them; that touches a shared interface. | Nice-to-have | If another module needs to import them | Open |
| OI-022 | **Tests use `unittest`** in the existing repository because pytest was not installable in the earlier sandbox. Sprint 2 later added `pytest.ini` and the final local run reports 113 tests passing. Revisit the remaining test-runner/documentation assumptions when CI is established. | Nice-to-have | When CI/test running is set up | Open |
| OI-023 | **README/docs cleanup after removing `prefilter.py`.** The history explicitly says `prefilter.py` was removed because it duplicated cache semantics and could conflict with the core security ordering. The README should also list `tiers/model_selector.py`; that cleanup is outside this docs-registry-only pass. | Should-fix | Next non-docs cleanup pass | Open |
| OI-024 | **Removed `session/prefilter.py`.** Not in the architecture or research traceability, and a session-level "already answered" shortcut could conflict with the core principle. Exact-match caching stays in `tiers/cache_lookup.py`. | — | — | Resolved (file deleted) |
| OI-025 | **Removed duplicate `logging/` directory.** Could have shadowed Python's stdlib `logging`; `metrics.py` lives under `audit/` per the repository structure. | — | — | Resolved (directory deleted) |
| OI-026 | **Session audit snapshot is not yet in the real audit record.** The Sprint 3 history identified that `session_state.py` currently writes its per-turn snapshot only through Python's standard logger, while Stage 7 requires the session snapshot to become part of the structured audit record. This is part of the Sprint 3 wiring/audit rollout, not a separate architecture change. | Should-fix | Sprint 3 wiring pass | Open |

## Taxonomy / scope decisions captured from the Sprint 2–3 history

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-027 | **Compound request decomposition remains deferred.** The detailed taxonomy intentionally covers single, classifiable requests across conventional computational structures, but splitting a compound request into subproblems and routing them independently would change the current single-request Stage 3 interface. It remains future work unless the owner approves a Change Proposal. | Decision needed | If compound-request failures become material to the evaluation | Open |
| OI-028 | **Do not treat the taxonomy as an exhaustive finite list.** `UNKNOWN` is a first-class audited computational-structure state and must continue through the normal cheapest-first ladder rather than silently meaning "send to LLM." This is now documented in `TAXONOMY.MD`. | — | — | Resolved (taxonomy policy documented) |

## Already scheduled in the plan (not duplicated here)

These were deliberately left unbuilt and already have a sprint in `EXECUTION_PLAN.md`:
Stage 4 feedforward (Sprint 4), graduated tier ladder and real small-classifier/RAG tiers
(Sprint 4), `escalation/repair_router.py`, validator, governance, `bias_monitor.py` (Sprint 5),
`modality_router.py` and full adversarial suites (Sprint 6), `cost/breakeven.py` and the comparative
experiment (Sprints 7–8). Also tracked in the plan: formal user-study design and its ethics/methodology
pass (needed before Sprint 7) and the full `policy/governance/` review workflow.
