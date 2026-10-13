# CP-001: Stage 7 audit record and request evidence

**Status:** Revised draft for owner decision. Nothing is implemented by this proposal; `ARCHITECTURE.md` remains frozen and unchanged.  
**Author:** ChatGPT (independent architecture/research review)  
**Implementation reviewer:** Claude  
**Decider:** Project owner under Rule 4  
**Date:** 2026-10-13

## Recommendation

**Accept the direction, subject to owner approval of the schema change described below.** Keep the permanent audit log free of request content; use a per-record-salted HMAC for text-request matching; retain the structured decision evidence required to explain routing and outcomes; do not build a separate diagnostics store or forensic evidence vault now.

This is a deliberate balance, not a claim that privacy-preserving logs can reconstruct every incident. A prompt-injection bypass that was never flagged cannot be reconstructed from a content-free record. That residual limitation must remain explicit.

## Part A — Evaluation and chosen design

### A.1 Current-state findings

The repository review found:

- `audit/audit_log.py::log_decision` is the only identified audit-log writer, called by `api/main.py`.
- No production audit-log reader was found. This is a qualified finding, not proof: GitHub code search can miss dynamic paths or unindexed references.
- The audit log currently does **not** store request text. It records a nested routing decision and a subset of Stage 7 fields.
- Tests in audit, API, session, cost, language, and modality areas read audit records or call `log_decision`. Exact-key and shape assertions must be updated for schema version 2.
- Stage 0 already exposes `normalized_text`, `confidence`, and `matched_patterns`. The Stage 3 `TierStep` already records tier, whether it should be attempted, reason, and estimate.
- `guardrails/output_filter.py` emits named reason identifiers rather than matched output substrings.
- `api/main.py` does not currently measure latency with a timer. The proposed latency field therefore requires an explicit measurement implementation; it must not be populated with an estimate or a fabricated value.
- Operational logging is a separate exposure path: validator exception messages may be written to application logs. Review and constrain those messages before production use; an audit-schema change alone does not solve this.

### A.2 Permanent audit record

The permanent append-only log should contain only what is needed to establish the runtime's decision chain and terminal outcome. It must not contain raw request text, pattern-redacted text, excerpts, n-grams, or copies of matched input.

For a text request, use this evidence shape:

```json
{
  "digest_alg": "hmac-sha256",
  "digest": "<hex HMAC>",
  "salt": "<random per-record salt, hex encoded>",
  "key_id": "<configured key version>",
  "normalization_version": "<Stage 0 normalization version>",
  "normalized_char_len": 142,
  "raw_text_stored": false,
  "status": "available"
}
```

- Compute `HMAC-SHA-256(key, salt_bytes || UTF8(normalized_text))`, using a cryptographically secure random salt of fixed length for every record. The fixed-length salt makes the input framing unambiguous.
- `normalized_char_len` means the number of Unicode code points in the Stage 0 normalized text, not bytes and not grapheme clusters.
- The digest is of the normalized text that informs downstream policy/routing, not a claim that the original request can be reconstructed.
- If normalized text is unavailable (for example, a non-text ingress refusal or a Stage 0 failure before normalization), set the digest and length to null and use a defined `status` such as `not_text_input` or `normalization_unavailable`. Never fall back to storing or digesting arbitrary attachment payloads.
- If the configured key or secure salt generation is unavailable, do not fall back to plain SHA-256, a random per-process key, or a silently omitted digest. Preserve the existing fail-loud audit-write requirement.
- Keep key material outside the log and separate from session/checkpoint secrets. `key_id` identifies the key needed for later verification. If historical verification is required, old keys must remain securely available for as long as those records are retained.
- Per-record salts prevent simple equality comparison of digests across records and make a reporter-supplied request verifiable by scanning records. They do **not** protect against an attacker who obtains both the HMAC key and the log; such an attacker can test guesses against individual records. Key compromise and key loss remain explicit risks.

A deterministic cross-session digest is not justified by a current requirement. Repeat-attack detection belongs in session state or structured pattern/rule outcomes, not in the permanent request digest.

### A.3 Structured evidence and scope

The audit record should include the Stage 7 decision evidence already required by the frozen specification: Stage 0 verdict, confidence and matched-pattern identifiers; Stage 1 policy flags; session snapshot; cheaper-tier attempts/skips and reasons; selected tier, estimated cost and rationale; actual execution latency where measured; validation outcome and trace; escalation events; checkpoint requirement; and final outcome.

Do not add request excerpts. Do not add classifier-style tags or other inferred user attributes to the permanent log in this change. Their value for production bias analysis has not been demonstrated, and the classifier's correctness cannot be established from unlabeled production records. Continue using labeled fixtures and evaluation sets for calibration and bias evaluation. Aggregate production outcomes may help identify where to investigate, but are not ground-truth accuracy measurements.

No separate short-retention diagnostics store is proposed for the MVP. Adding another store would introduce another retention, access-control, and deletion surface before the need is established. Structured reason codes needed for Stage 7 remain in the permanent decision record; optional diagnostic features are deferred.

### A.4 Schema semantics to approve

The new schema is version 2. Existing lines without `schema_version` are treated as version 1 and remain untouched. New records must include all v2 fields, using documented null/empty values when a stage did not run.

| Field | V2 meaning |
|---|---|
| `schema_version` | Integer `2` for new records. |
| `request_evidence` | The evidence object defined in A.2; never request content. |
| `stage0_screen_result` | Existing verdict string, retained for a smaller migration. |
| `stage0_confidence`, `stage0_matched_patterns` | Values already returned by Stage 0; pattern names only, never matched text. |
| `policy_flags` | Top-level copy of Stage 1 flags to match the target schema. It must equal the nested legacy value while that value remains during migration. |
| `session_state_snapshot` | Existing session snapshot. |
| `alternatives_considered` | The existing Stage 3 plan steps: tier, attempt/skip status, reason, and estimate. Reason fields must remain identifiers/controlled explanations, not copies of input. |
| `selected_tier`, `estimated_cost`, `rationale` | Top-level Stage 3 values. Preserve the existing nested `decision` object temporarily for compatibility; tests must assert the duplicated values agree. |
| `actual_cost` | `latency_ms` is measured Stage 5 wall-clock execution time across attempted tiers; null if Stage 5 did not run. `energy_wh` and `dollars` are null until genuinely measured. Null means unavailable/not measured, never zero. |
| `feedforward_returned` | True only when the server includes a feedforward message in its API response. Do not claim that the user actually saw/rendered it; the server cannot observe that. This replaces the misleading target name `feedforward_shown`. |
| `user_confirmation_state` | `not_required`, `pending`, or `confirmed`. A valid confirmation token consumed is `confirmed`; a response awaiting confirmation is `pending`. Cancellation/modification is not claimed because the current server cannot observe those client actions. This replaces an ambiguous boolean/tri-state `user_confirmed`. |
| `validation_result` | Summary enum: `passed`, `failed`, `validator_error_failed_open`, `validator_error_failed_closed`, or `not_run`. Keep `validation_trace` for detail. A normal failed check is not “failed open”; that term applies only when the validator itself errors and policy permits release. |
| `escalations` | Actual tier transitions/repair escalations observed by the pipeline, not inferred from the planned attempt order alone. |
| `human_checkpoint_triggered`, `checkpoint_kinds` | Whether a checkpoint was required and why (for example `human_required` or `cost_gate`). This does not claim a human reviewed the output. |
| `final_outcome`, `outcome_reason` | `final_outcome` is the stable state enum `released`, `blocked`, `pending_confirmation`, or `withheld`. `outcome_reason` carries the existing controlled block/withhold reason code, keeping the enum from duplicating every failure reason. |
| Existing execution fields | Retain `timestamp`, `session_id`, `execution`, `validation_trace`, and `withheld_route_estimate`. Keep the nested `decision` snapshot temporarily as noted above. |

This proposal deliberately does not add calibrated validator confidence, energy/dollar measurements that do not exist, user cancel/modify events the server cannot observe, or human-review outcomes for a workflow that is not implemented.

### A.5 Investigation limits

| Question | Permanent v2 record |
|---|---|
| Which rules, route, escalation, validation result and terminal outcome were recorded? | Yes |
| Does a reporter-supplied text match a text record? | Yes, by recomputing the salted HMAC using the correct key and scanning records |
| Was a flagged request a false positive? | Partly; the rule/pattern evidence is present, but the original text is not |
| Can an unflagged prompt-injection bypass discovered later be reconstructed? | No, unless the requester/reporting party or a separate test corpus supplies the input |
| Can production logs alone establish classifier accuracy or bias ground truth? | No; labeled evaluation data are still required |
| Can the system prove a user saw a feedforward message or cancelled in the UI? | No; it records only server-observable response/confirmation state |

This lost forensic capability is an accepted limitation of the privacy-preserving default, not something the digest solves. Mitigations are reporter-supplied reproductions, adversarial suites, and better structured decision evidence. None can recover a request that was never retained.

### A.6 Forensic vault decision

Do not build Level 3 now. A separate encrypted, access-controlled, time-limited evidence store would be a new data-governance subsystem, not a small extension to JSONL logging. Reconsider only when a concrete incident class cannot be investigated adequately with the permanent record and supplied reproductions. Any future proposal must define authorization, case tracking, access logging, encryption/key separation, retention/deletion verification, user disclosure, and who may activate capture. Any capture would be forward-only and must not silently become default logging.

## Part B — Change Proposal

**Component:** Stage 7 target audit schema in `ARCHITECTURE.md`; implementation in `audit/audit_log.py` and `api/main.py`.

**Current behavior:** The frozen target schema includes `request`, but the current implementation does not write request text. The implementation logs a subset of the target schema, including a nested `decision`, Stage 0 verdict, session snapshot, execution state, withheld route estimate, and validation trace.

**Proposed behavior:** Replace the target `request` field with `request_evidence`; version the schema; add the verified Stage 0 and Stage 1 evidence and missing Stage 7 fields with the semantics defined in Part A; retain existing execution/validation fields; do not add a forensic vault or request-content retention.

**Why necessary:**
1. **Research:** NIST's AI RMF GenAI Profile recommends documented after-action review of incidents (GV-1.5-002), retention policies for testing/evaluation/validation/verification history (GV-1.5-003), and consideration of sensitive-data rights in system inventories (GV-1.6-003). This supports governed evidence retention and explicit sensitive-data handling; it does not prescribe HMAC, salting, or this schema.
2. **Security/privacy:** Permanent raw or redacted request retention creates an avoidable repository of credentials and personal data. Pattern redaction is not a reliable guarantee. The chosen digest supports matching without storing content.
3. **Engineering:** The target schema is only partly implemented. Versioning and explicit null/enum semantics prevent absent, unmeasured, pending, and failed states from being conflated.
4. **Resource efficiency:** The added evidence is derived from existing pipeline decisions; only Stage 5 latency measurement is new instrumentation. No AI call or new data store is introduced.

**Existing components affected:** `audit/audit_log.py`, `api/main.py`, settings/key configuration, audit/API/session/cost/language/modality tests, and the target schema in `ARCHITECTURE.md`. No production reader was found, but the search limitation is documented in A.1.

**Change categories:** Interfaces/shared data shape and evaluation methodology. Stage purposes, stage ordering, and runtime policy semantics remain unchanged.

**If not changed:** The target schema remains ambiguous about request retention and the implementation continues to log only a subset of the required decision chain.

**Required implementation checks after approval:**
1. Enumerate and update tests that assert exact audit-record keys or field shapes.
2. Test HMAC generation, per-record salt uniqueness, key ID, normalization version, unavailable-text states, key/salt failure behavior, and verification of a reporter-supplied request.
3. Add a high-entropy canary request containing secret-like text and assert that the raw canary is absent from the entire serialized record, including rationale and trace fields.
4. Ensure reason/trace fields contain only controlled identifiers and explanations, never matched request/output substrings.
5. Verify each v2 terminal path writes the complete schema and correct null/enum states.
6. Review application exception logging separately so exception messages cannot reintroduce user content into operational logs.
7. Do not claim the audit schema change is implemented until code, tests, and the CI workflow confirm it.

**Decision:** Pending explicit owner decision under Rule 4.  
**Recommendation:** Accept this bounded schema change; keep Level 3 deferred.
