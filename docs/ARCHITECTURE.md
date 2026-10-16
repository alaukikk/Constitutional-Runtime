# Constitutional Runtime — Architecture Specification v1.0

**Status: FROZEN.** This document is the authority. Neither Claude nor
ChatGPT may implement or recommend a deviation from this document
without first submitting a Change Proposal (see `CONSTITUTION.md`) and
receiving explicit approval from the project owner.

Where a field below is marked `TBD`, it means real data doesn't exist
yet (e.g. real cost numbers) — that is expected at this stage and is
not itself grounds for a change proposal. Filling in `TBD` fields with
real values as sprints progress does not require a change proposal;
changing the *structure* of a stage does.

---

## Core principle governing all stages

> **A stateless, per-message security screen runs first, unconditionally,
> on every request's literal text, with zero input from session
> history. Session-derived context may only ever *tighten* constraints
> on top of that screen's decision — it may never loosen or bypass it.
> Cache is a tier evaluated during routing, never a shortcut that skips
> the screen, and only ever serves on an exact match of the normalized
> current message.**
>
> The security gates may evaluate derived matching views of the request.
> Everything downstream of the gates (classifier, tier, cache, confirmation
> token, audit digest) continues to use normalized text. The text a model
> receives is therefore not equivalent to the text the gates evaluated, and
> gate decisions are not a guarantee about what the model reads.

This resolves the trust-boundary question raised during architecture
review: an attacker cannot use accumulated "harmless-looking" session
history to get a later malicious request routed around the security
gate, because the gate never looks at session history to begin with.

---

## Stage 0 — Minimal Trusted Ingress

1. **Purpose:** Normalize input and run the stateless jailbreak/injection screen before anything else touches the request.
2. **Input:** Raw request text (and, later, other modalities).
3. **Output:** Normalized text + a screen verdict (clean / suspicious / blocked) + confidence score + derived matching views used only for Stage 0/1 pattern matching. Matching views are not persisted, cached, digested, or passed to a tier.
4. **Allowed computational methods:** Regex/heuristic pattern matching (Sprint 1). Adversarially-tested classifier (later sprint, owned by security).
5. **AI permitted:** No. This stage must remain cheap and non-intelligent by design — an ML/LLM-based characterizer running before this point would itself become ungated attack surface.
6. **Security boundary:** This *is* the security boundary for the raw request. Runs on every path without exception.
7. **Failure behavior:** Fail closed. If the screen errors or times out, block the request.
8. **Cost accounting:** Must be near-zero cost; if this stage's own overhead becomes non-trivial, that's a `breakeven.py` finding worth flagging.
9. **Audit requirements:** Every verdict (including "clean") is logged with matched patterns/confidence.
10. **Escalation conditions:** Suspicious → flagged for the policy gate. Blocked → response returned immediately, no further stages run.
11. **Research gap addressed:** Jailbreak literature — attacks are cheap and don't require model access, so filtering upstream of any model call matters more than downstream alignment tuning.
12. **How we will test it:** Adversarial payload suite (`guardrails/adversarial/`) run as a permanent regression test, not a one-off check. Matching-view changes additionally require a benign-corpus new-match audit: every new benign match must be justified or removed, and unreviewed report changes fail CI.

**Owner:** Security specialist. **Sprint 1 status:** basic regex version implemented (`guardrails/injection_screen.py`).

---

## Stage 1 — Constitutional Policy Gate

1. **Purpose:** Apply the actual rulebook to the request, on every path.
2. **Input:** Normalized text + Stage 0 verdict + optional Stage 0 matching views. With no views supplied, matching uses normalized text only.
3. **Output:** List of `PolicyFlag`s + a single most-severe `PolicyAction` (allow/flag/require_human/block).
4. **Allowed computational methods:** Keyword/rule matching (Sprint 1). More robust matching later — interface (`list[PolicyFlag]` out) stays stable regardless.
5. **AI permitted:** No, by default. Policy rules are declarative (`constitution.yaml`), not model-based judgment.
6. **Security boundary:** Applies to **every** execution path, including the deterministic/non-AI branch. A cached or rule-based answer is not exempt from data-privacy or content rules.
7. **Failure behavior:** Declared **per rule** in `failure_modes.yaml` — e.g. data-privacy and dangerous-content rules fail closed; low-risk, latency-sensitive rules may fail open. Never a single global setting.
8. **Cost accounting:** `TBD` — negligible expected, to be measured.
9. **Audit requirements:** Every triggered flag logged with rule ID, risk category, action, and reason.
10. **Escalation conditions:** `BLOCK` → immediate response, no further stages. `REQUIRE_HUMAN` → flows through, but Stage 4/7 must enforce a human checkpoint before or after execution respectively.
11. **Research gap addressed:** NIST AI RMF GenAI Profile risk categories; OWASP LLM Top 10 (Sensitive Information Disclosure applies regardless of which tier answers).
12. **How we will test it:** Golden test set of requests with expected flags; every PR must not regress this set. Matching-view changes additionally require transformation-specific benign/adversarial tests and a reviewed new-match audit.

**Owner:** Security specialist. **Sprint 1 status:** implemented (`policy/engine.py`, `config/constitution.yaml`, `config/failure_modes.yaml`).

---

## Stage 2 — Session Context

1. **Purpose:** Track cumulative risk/cost across a conversation, closing multi-turn blindness.
2. **Input:** Session ID, current request, Stage 0/1 verdicts.
3. **Output:** Updated `SessionState` (cumulative cost, cumulative risk score, turn count) + any *additional* constraints this turn should carry.
4. **Allowed computational methods:** Simple running totals and thresholds.
5. **AI permitted:** No.
6. **Security boundary:** **May only add constraints, never remove or relax ones Stage 0/1 already set.** This is the explicit fix for the trust-boundary gap raised in architecture review.
7. **Failure behavior:** Fail open on read errors (treat as a fresh session) but log the failure — losing session memory should degrade to "less context," not "block the user."
8. **Cost accounting:** `TBD`.
9. **Audit requirements:** Session state snapshot logged per turn.
10. **Escalation conditions:** Cumulative risk/cost crossing a threshold → forces stricter routing (e.g. mandatory human checkpoint) regardless of what this single message looks like in isolation.
11. **Research gap addressed:** Neither the original draft architecture nor the merged ChatGPT/Claude version tracked anything across turns — identified as a gap during the "is this airtight" review.
12. **How we will test it:** Multi-turn adversarial scenarios where risk builds gradually across seemingly-harmless individual messages.

**Owner:** TBD (triage/cost track). **Sprint 1 status:** not implemented (stub only).

---

## Stage 3 — Necessity & Cost Router (Task Characterization + Routing)

1. **Purpose:** Classify the request and select the cheapest tier that can reliably handle it.
2. **Input:** Normalized text, classification confidence, `SessionState`, `MODEL_CATALOG`.
3. **Output:** `RoutingDecision` (selected tier, selected model if applicable, rationale, cost estimate, policy flags carried through).
4. **Allowed computational methods:** Cache lookup (exact match only — see core principle above) → deterministic/rule-based → small classifier → small RAG model → LLM (low reasoning) → LLM (high reasoning). Tiers are tried cheapest-first; a tier may only be skipped with a logged, documented reason.
5. **AI permitted:** Yes, from the small-classifier tier upward — but only after Stages 0–2 have passed.
6. **Security boundary:** The router and classifier are themselves attack surface — an adversary who learns how requests get scored could craft input to be misclassified into a weaker-scrutiny path. Requires its own adversarial test suite (`guardrails/adversarial/router_attack_suite.py`, `classifier_attack_suite.py`), separate from testing the LLM itself.
7. **Failure behavior:** If classification fails/errors, default to the most conservative tier (escalate up), not the cheapest.
8. **Cost accounting:** Every candidate tier gets a `TierCostEstimate` (energy/dollar/latency) before selection — this is the actual mechanism behind "cheapest adequate method."
9. **Audit requirements:** Full rationale for the selected tier, including which cheaper tiers were tried and rejected and why.
10. **Escalation conditions:** A tier reporting it can't handle the request (`None`) escalates to the next tier automatically.
11. **Research gap addressed:** The LLM-agents survey names "is this too simple to decompose" as an explicitly unresolved gap in existing agent frameworks. The GPT-5 case study shows reasoning depth is a continuous cost dial (7x swing), not a binary AI/no-AI switch. NIST's harmful-bias category applies here too — a classifier performing worse on non-English/informal phrasing would be a fairness failure hiding inside the efficiency layer (`bias_monitor.py`).
12. **How we will test it:** Labeled "golden set" of requests with expected tier assignments, including deliberate "should NOT escalate" cases; bias comparison across phrasing styles/languages.

**Owner:** Triage/cost track. **Sprint 1 status:** tier functions exist as stubs; no real classification or scoring logic yet (`triage/` largely unbuilt).

---

## Stage 4 — Feedforward Checkpoint

1. **Purpose:** Show the user what's about to happen *before* it happens, not just log it.
2. **Input:** `RoutingDecision` from Stage 3.
3. **Output:** A user-facing message: selected tier/model, rationale, and (for high-cost/high-stakes cases) a hard confirm gate.
4. **Allowed computational methods:** Templated message generation from the `RoutingDecision` object. No AI needed.
5. **AI permitted:** No.
6. **Security boundary:** N/A (user-facing, not a security gate).
7. **Failure behavior:** Fail open for low-stakes categories (proceed without explicit confirmation); fail closed (require confirmation) for anything flagged `REQUIRE_HUMAN` upstream.
8. **Cost accounting:** N/A — this stage doesn't consume model resources.
9. **Audit requirements:** Log whether the server returned a feedforward message and the server-observable confirmation state. Do not claim the user saw/rendered the message or infer whether they proceeded, modified, or cancelled in the UI.
10. **Escalation conditions:** A cancellation may be logged as a user-initiated stop only if the server receives an explicit, trustworthy cancellation event. The current API cannot observe UI cancellation or modification, so neither is inferred from a missing confirmation or an abandoned request.
11. **Research gap addressed:** The metacognition paper's "feedforward" design as the actual mitigation for processing-fluency bias — intervention must happen *before* generation, since fluent output is what erodes scrutiny *after* it exists. Directly ties to the critical-thinking paper's finding that confidence in AI (not accuracy) predicts reduced scrutiny.
12. **How we will test it:** User study replicating the critical-thinking paper's method at small scale — compare self-reported scrutiny/calibration with vs. without this stage.

**Owner:** Validation/interface track. **Sprint 1 status:** not implemented.

---

## Stage 5 — Minimum-Sufficient Execution

1. **Purpose:** Actually answer the request, using the tier selected in Stage 3.
2. **Input:** Normalized text, selected tier/model.
3. **Output:** Raw response text.
4. **Allowed computational methods:** Whatever the selected tier specifies. For the LLM tier: a unified gateway (LiteLLM) across providers, with a configurable reasoning-depth parameter.
5. **AI permitted:** Yes, at the tier selected — never a tier "above" what Stage 3 selected without a logged escalation event.
6. **Security boundary:** Modality-aware — text, image, and audio inputs carry distinct cost/risk profiles; assuming the text pipeline's logic transfers to other modalities is an explicitly named gap (cross-modal injection).
7. **Failure behavior:** A tier execution error triggers `escalation/repair_router.py` — retry at a higher tier, not a silent failure.
8. **Cost accounting:** Actual (not estimated) cost/latency measured post-execution and compared against the Stage 3 estimate, feeding calibration.
9. **Audit requirements:** Actual tokens/cost/latency logged, tier used, model used.
10. **Escalation conditions:** Execution failure or low-confidence output → escalate per `escalation/repair_router.py` rules.
11. **Research gap addressed:** OWASP's "Unbounded Consumption" — this stage is the actual enforcement point that prevents uncontrolled resource expenditure per query, by construction (it only ever executes the tier Stage 3 selected).
12. **How we will test it:** Cost/latency measured against baseline "always call the LLM directly" comparison, per the Sprint 6 evaluation plan.

**Owner:** Execution/models track. **Sprint 1 status:** all tiers below LLM stubbed to return `None`; LLM tier returns a fake response (always succeeds, since it's the last resort).

---

## Stage 6 — Output Validator

1. **Purpose:** Check the response before it reaches the user.
2. **Input:** Raw response text, original request, selected tier.
3. **Output:** Pass/fail + confidence score + (on fail) a reason for `escalation/repair_router.py`.
4. **Allowed computational methods:** Prefer non-LLM checks (`validation/non_llm_checks.py`) — schema validation, rule-based checks, retrieval-grounded fact-check — wherever they suffice.
5. **AI permitted:** Only where non-LLM checks genuinely can't do the job. **If the validator itself is LLM-based, it is not exempt from the same risk categories, cost accounting, and audit logging as any other model invocation in this system.** This is a deliberate, non-negotiable rule — it directly answers the "who validates the validator" gap.
6. **Security boundary:** Same policy gate rules apply to the validator's own output if it's model-generated.
7. **Failure behavior:** Fail closed for high-stakes categories (don't return an unvalidated high-stakes answer); may fail open for low-stakes categories under latency pressure, per `failure_modes.yaml`.
8. **Cost accounting:** Logged like any other AI invocation if LLM-based.
9. **Audit requirements:** Full validation result, including which check type (LLM vs. non-LLM) was used and why.
10. **Escalation conditions:** Fail → `escalation/repair_router.py` decides retry-at-higher-tier vs. drop-to-human.
11. **Research gap addressed:** Explicit architecture-review gap: "who validates the validator" — LLM-as-judge doesn't eliminate the reliability/cost/safety problem, it just moves it up a level.
12. **How we will test it:** Validator accuracy measured against a labeled set of known-good/known-bad outputs; confirm LLM-based validator calls appear in cost/audit logs identically to primary calls.

**Owner:** Validation/interface track. **Sprint 1 status:** not implemented.

---

## Stage 7 — Human Checkpoint & Audit

1. **Purpose:** Final human confirmation where required, plus permanent record-keeping and the feedback loop that recalibrates the whole system.
2. **Input:** Validated response, all upstream decisions/flags.
3. **Output:** Final response to user + a permanent audit record + (if governance-relevant) an entry in the policy change log.
4. **Allowed computational methods:** N/A for the human-checkpoint half; structured logging (JSON Lines in Sprint 1, real DB later) for audit.
5. **AI permitted:** No.
6. **Security boundary:** Enforces NIST's automation-bias risk category directly — for judgment/high-stakes categories, the human must actively confirm or edit, not passively accept ("stewardship," not rubber-stamping).
7. **Failure behavior:** Audit-write failures fail loud (alert), never silent — losing the audit trail defeats the point of the whole system.
8. **Cost accounting:** N/A.
9. **Audit requirements:** This *is* the audit requirement for every other stage. Record schema (see below) must capture the full decision chain, not just the final outcome.
10. **Escalation conditions:** N/A — this is the terminal stage.
11. **Research gap addressed:** NIST's automation-bias category; the critical-thinking paper's "stewardship" framing (accountability stays with the human even when production is delegated).
12. **How we will test it:** Confirm every audit record contains the full schema below; confirm human checkpoints actually block completion until confirmed for flagged categories.

**Audit record schema (v2 — accepted by CP-001 on 2026-10-13; implemented and exercised by the Sprint 6 test suite):**
```json
{
  "schema_version": 2,
  "timestamp": "...",
  "session_id": "...",
  "request_evidence": {
    "digest_alg": "hmac-sha256",
    "digest": "<hex HMAC or null>",
    "salt": "<per-record random salt or null>",
    "key_id": "<configured key ID or null>",
    "normalization_version": "<Stage 0 version or null>",
    "normalized_char_len": "<Unicode code-point count or null>",
    "raw_text_stored": false,
    "status": "available | not_text_input | normalization_unavailable"
  },
  "stage0_screen_result": "...",
  "stage0_confidence": null,
  "stage0_matched_patterns": [],
  "policy_flags": [],
  "session_state_snapshot": {},
  "alternatives_considered": [],
  "selected_tier": null,
  "estimated_cost": null,
  "rationale": "...",
  "actual_cost": {
    "latency_ms": null,
    "energy_wh": null,
    "dollars": null
  },
  "feedforward_returned": false,
  "user_confirmation_state": "not_required | pending | confirmed",
  "validation_result": "passed | failed | validator_error_failed_open | validator_error_failed_closed | not_run",
  "validation_trace": [],
  "escalations": [
    {"kind": "ladder_fallthrough | repair", "from_tier": "...", "to_tier": "...", "reason": "..."}
  ],
  "human_checkpoint_triggered": false,
  "checkpoint_kinds": [],
  "final_outcome": "released | blocked | pending_confirmation | withheld",
  "outcome_reason": "...",
  "execution": "...",
  "withheld_route_estimate": null,
  "decision": {}
}
```

**Owner:** Audit/logging track. **Implementation status:** schema v2 is implemented in `audit/audit_log.py` and `audit/request_evidence.py`; the live pipeline audit-schema tests cover terminal paths and the documented null/enum states. Existing JSONL records without `schema_version` remain v1 and are not rewritten. New records use the v2 shape. `NORMALIZATION_VERSION = "1"` is pinned by `tests/guardrails/test_normalization_golden.py`; the golden table records existing behavior and does not certify that behavior as secure. Escalation events distinguish `ladder_fallthrough` from `repair`. Audit appends are serialized within one process by `_WRITE_LOCK`; this is not multi-process-safe. CP-001 check #6 remains open as OI-084: application exception logging must be reviewed separately. See `docs/proposals/CP-001-stage7-audit-record.md` for request-evidence, key-handling, and migration requirements.

---

## Escalation & repair — cross-cutting, not a single stage

Escalation/repair edges run **stage-to-stage**, not only after final output validation:
- Stage 1 block → immediate return, no further stages.
- Stage 3 tier returns `None` → automatically try next tier (this is normal operation, not a failure).
- Stage 5 execution error → `escalation/repair_router.py` decides retry-at-higher-tier vs. escalate-to-human.
- Stage 6 validation failure → same repair router, same decision space.

## Meta-cost accounting — cross-cutting, not a single stage

`cost/breakeven.py` continuously measures: (sum of Stage 0–4 + Stage 6 overhead) vs. (savings from not always calling the most expensive tier). This is a first-class research question for the capstone, not an implementation nicety — see `RESEARCH_TRACEABILITY.md`.
