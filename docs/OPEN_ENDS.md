# Open Items

The single register of anything we said we'd come back to: known gaps,
deferred decisions, cleanups, and things to verify. If it isn't here, it
isn't tracked. `EXECUTION_PLAN.md` points to this file instead of keeping
its own list, so the two can't drift apart.

Adding or resolving an item does **not** need a Change Proposal. If an
item's *resolution* would change a stage's structure, a shared interface
in `policy/schemas.py`, or the runtime constitution, it is marked
**Decision needed** and goes through `CONSTITUTION.md` first (Rules 2 and 4).

Created 2026-09-28, during Sprint 3.

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
Sprint 3 closes with the wiring pass (see OI-013 to OI-016).

---

## From Sprint 1 (Skeleton)

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-001 | **Verify repo state vs. plan.** In the snapshot shared this session, these files were empty: `api/main.py`, `policy/engine.py`, `guardrails/injection_screen.py`, `config/constitution.yaml`, `config/failure_modes.yaml`, `tiers/cache_lookup.py`, `triage/*`. `tiers/deterministic.py` is still a stub returning `None`. `EXECUTION_PLAN.md` marks the Sprint 1 items done and Sprint 2 targets cache/deterministic/taxonomy/classifier. Either the snapshot was stale or those files never got saved. | Must-fix | Start of next session | Open |
| OI-002 | **Stage 0 screen is basic regex.** The adversarially-tested classifier is a later-sprint, security-owned item. | Should-fix | Sprint 6 (adversarial hardening) | Open |
| OI-003 | **Stage 1 is keyword matching only.** Interface (`list[PolicyFlag]`) is meant to stay stable when matching improves. | Should-fix | Sprint 5–6 | Open |
| OI-004 | **Stage 0 checkpoint in `api/main.py` is an unplugged placeholder.** Nothing currently runs the screen before routing. | Must-fix | Sprint 3 wiring pass (see OI-013) | Open |
| OI-005 | **`cost/model_registry.py` holds fake placeholder data** (`stub-small/medium/large`). | Should-fix | While building `cost/estimator.py` | Open |
| OI-006 | **`tiers/llm_call.py` returns a fake response.** Real integration is deferred (see OI-010). | Should-fix | After hypothesis validated on 1–2 models | Open |
| OI-007 | **Audit log records a subset of the Stage 7 schema.** Also, the two docs disagree on timing: `ARCHITECTURE.md` says "Sprint 2+", `EXECUTION_PLAN.md` says Sprint 6. Pick one and align both. | Should-fix | Sprint 6, or sooner if estimator output needs logging | Open |
| OI-008 | **`TBD` fields in `ARCHITECTURE.md`** (cost accounting for Stages 1 and 2, Stage 2 owner) should be filled with measured values or named owners as they become known. No Change Proposal needed. | Nice-to-have | As each is measured | Open |
| OI-009 | **`requirements.txt` isn't valid pip format.** It has "— explanation" text after each package name, so `pip install -r` will fail. Move the comments to `#` lines. | Should-fix | Before anyone else installs the project | Open |

## From Sprint 2 (First real tiers)

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-010 | **LiteLLM / multiple real providers** deliberately deferred. Infrastructure, not the research contribution. | Nice-to-have | After core hypothesis validated with 1–2 models | Open |
| OI-011 | **Golden set of ~20–30 hand-labeled requests** started in Sprint 2 must be carried forward and cleaned up for the real experiment. | Must-fix | Sprint 7 | Open |
| OI-012 | **`EXECUTION_PLAN.md` has no Sprint 2 status.** Sprint 1 says COMPLETE; Sprint 2 doesn't. Update the tracker so it reflects reality (this also depends on OI-001). | Should-fix | Next doc edit | Open |

## From Sprint 3 (Session context + cost accounting)

Items found while building `session/session_state.py`.

| ID | Item | Severity | Trigger | Status |
|---|---|---|---|---|
| OI-013 | **Session ID rotation.** If clients choose their own session ID, they can restart with a clean history on every request and bypass Stage 2. `session_state.py` cannot fix this. Fix: server-issued or signed session IDs in `api/main.py`, plus an end-to-end test that tries to rotate. | Must-fix | Sprint 3 wiring pass; before any red-team | Open |
| OI-014 | **Blocked turns must still be recorded.** `api/main.py` must call `record_turn` before returning on a Stage 0/1 block, since blocked probes are what should accumulate. Add a test asserting blocked turns increment the session. | Must-fix | Sprint 3 wiring pass | Open |
| OI-015 | **How the session floor reaches `RoutingDecision`.** Proposed workaround: `triage/decision.py` converts the floor into a `PolicyFlag` (e.g. `rule_id="session.cumulative_risk"`) appended to `policy_flags`, so no schema change. If the owner disagrees, a Change Proposal is needed. | Decision needed | When building `triage/decision.py` | Open |
| OI-016 | **Wire `record_turn` into the request path and run the multi-turn scenario for real** (turn 3 tightens although harmless alone). Bundles OI-004, OI-013, OI-014 into one pass. | Must-fix | End of Sprint 3, after `estimator.py` and `model_selector.py` | Open |
| OI-017 | **Energy is missing from the cost interfaces.** The audit schema and Stage 3 spec call for `energy_wh`, but `TierCostEstimate` has only dollars and latency, and `ModelInfo` has no energy field. Adding one changes `policy/schemas.py`, so it likely needs a Change Proposal (or a documented decision to keep energy out of scope). | Decision needed | Start of `cost/estimator.py` | Open |
| OI-018 | **Session thresholds are placeholders** (`require_human_risk=4`, `block_risk=12`, `require_human_cost=$1`). Calibrate against golden-set and cost data. | Should-fix | Sprint 7 | Open |
| OI-019 | **No risk decay** (risk is monotonic by design, since decay is a form of loosening). Long benign sessions with a few mild flags will eventually escalate. Revisit only if false escalations show up in testing; changing it may need a Change Proposal. | Decision needed | If golden-set testing shows false escalations | Open |
| OI-020 | **In-memory store is unbounded and the lock is single-process.** Replace with a Redis-backed `SessionStore` with atomic updates. Eviction must not reset a session. | Nice-to-have | Post-capstone, unless the demo needs it | Open |
| OI-021 | **`SessionState`/`SessionConstraints` live in `session_state.py`, not `policy/schemas.py`.** Move only if other modules need them; that touches a shared interface. | Nice-to-have | If another module needs to import them | Open |
| OI-022 | **Tests use `unittest`** (pytest wasn't installable in the dev sandbox). Run from repo root; add an empty root `conftest.py` if bare `pytest` fails to import. | Nice-to-have | When CI/test running is set up | Open |
| OI-023 | **README and plan cleanup after removing `prefilter.py`.** Remove it from the README and the Sprint 3 list in `EXECUTION_PLAN.md`; add `tiers/model_selector.py` to the README `tiers/` list, since it's missing. Replace `EXECUTION_PLAN.md`'s "Open items" section with a pointer to this file. | Should-fix | Next doc edit | Open |
| OI-024 | **Removed `session/prefilter.py`.** Not in the architecture or `RESEARCH_TRACEABILITY.md` (Rule 3), and a session-level "already answered" shortcut would conflict with the core principle. Exact-match caching stays in `tiers/cache_lookup.py`. | — | — | Resolved (file deleted) |
| OI-025 | **Removed duplicate `logging/` directory.** Could have shadowed Python's stdlib `logging`; `metrics.py` lives under `audit/` per the README. | — | — | Resolved (directory deleted) |

## Already scheduled in the plan (not duplicated here)

These were deliberately left unbuilt in Sprint 1 and already have a sprint in `EXECUTION_PLAN.md`:
Stage 4 feedforward (Sprint 4), graduated tier ladder and real small-classifier/RAG tiers (Sprint 4),
`escalation/repair_router.py`, validator, governance, `bias_monitor.py` (Sprint 5),
`modality_router.py` and full adversarial suites (Sprint 6), `cost/breakeven.py` and the comparative
experiment (Sprints 7–8). Also tracked in the plan: formal user-study design and its ethics/methodology
pass (needed before Sprint 7) and the full `policy/governance/` review workflow.
