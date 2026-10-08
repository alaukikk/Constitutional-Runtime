# Capstone-Project

This repository contains the Constitutional Runtime capstone implementation: a runtime layer that evaluates requests, applies constitutional/security constraints, considers cheaper computational alternatives, and invokes progressively more capable methods only when required.

## Repository structure

`.github/CODEOWNERS` — GitHub-recognized code-owner enforcement copy

`api/` — the front door
- `main.py` — live Stage 0 → Stage 1 → Stage 2 → Stage 3/5 → Stage 6 → Stage 7 request pipeline
- `settings.py` — app-level settings (API keys, ports, checkpoint signing secret, session identity secret/limits, env variables)

`config/` — the rulebook, as data
- `constitution.yaml` — policy rules (what's allowed, blocked, flagged)
- `failure_modes.yaml` — what to do if a check times out or errors (block vs. allow)

`cost/` — figures out what things cost
- `calibration/calibration.py` — planned script to refresh cost numbers from real usage data
- `breakeven.py` — planned analysis of whether runtime overhead itself costs more than it saves
- `estimator.py` — estimates energy/dollar/latency/token cost for a request + tier/model, with explicit assumptions and uncertainty
- `model_registry.py` — model/cost catalog and energy anchors

`guardrails/` — the security layer
- `adversarial/classifier_attack_suite.py` — test inputs designed to trick the triage classifier
- `adversarial/router_attack_suite.py` — test inputs designed to trick the router into a weaker path
- `injection_screen.py` — catches prompt injection / jailbreak attempts before anything else runs
- `output_filter.py` — checks the final output for unsafe content

`interface/` — what the user sees / where human interaction gates live
- `confidence.py` — planned confidence presentation/communication layer
- `feedforward.py` — templated route preview/outcome text and the high-cost confirm gate
- `human_checkpoint.py` — confirm-before-execute gate for `REQUIRE_HUMAN`: single-use, signed tokens bound to session, exact text, and rule set

`llm/` — talks to the actual AI models
- `gateway.py` — planned raw API client (auth, retries, request/response format)

`audit/` — keeps a record
- `audit_log.py` — logs every decision made and why; records `execution`, validation trace, and withheld-route estimates
- `metrics.py` — tracks numbers over time (cost saved, escalation rate, etc.) and hosts offline evaluation metrics

`policy/` — enforces the rulebook
- `engine.py` — reads `constitution.yaml` and applies the rules
- `schemas.py` — defines the shared data shapes (what a decision or classification looks like)
- `governance/CODEOWNERS` — canonical project governance ownership copy
- `governance/change_log.py` — machine-readable constitutional-file governance/integrity log
- `governance/change_log.jsonl` — committed governance decision records and hashes

`session/` — remembers context across a conversation
- `identity.py` — server-issued, HMAC-SHA256-signed session tokens and issuance limits
- `session_state.py` — tracks cumulative risk/cost, turn count, and monotonic constraints across a conversation

`tests/` — automated tests, organized by module/stage as implementation grows

`tiers/` — the actual ways to answer a request, cheapest to priciest
- `cache_lookup.py` — return a previously-saved answer
- `deterministic.py` — rule-based / calculator / lookup answers, no AI involved
- `small_classifier.py` — a small, cheap model for simple categorization tasks
- `rag_small_model.py` — a small model with retrieved reference info to back its answer
- `llm_call.py` — full-LLM call stub (via `llm/gateway.py`); reasoning-depth control is planned (OI-006)
- `model_selector.py` — selects among candidate models using capability floors and energy/dollar objectives

`triage/` — decides what kind of request this is and where it should go
- `bias_monitor.py` — paired-request routing-outcome comparison harness; it does not establish fairness
- `classifier.py` — first-pass keyword classifier; its output feeds the Stage 3 planner in `decision.py`
- `decision.py` — the Stage 3 planner: builds the cheapest-first routing plan (cache → deterministic → small classifier → RAG → LLM) with per-rung skip reasons and cost estimates
- `modality_router.py` — implemented text-only ingress refusal boundary (Sprint 6); this is refusal, not multimodal support
- `taxonomy.py` — defines the categories used to classify requests

`validation/` — checks the answer before it's shown to anyone
- `non_llm_checks.py` — cheap, rule-based checks (preferred over using another AI call to check)
- `validator.py` — main Stage 6 validation logic

`escalation/`
- `repair_router.py` — decides whether a failed execution/validation path can be repaired or must be withheld

`docs/` — project control and research documentation
- `EXECUTION_PLAN.md` — sprint status and implementation plan
- `OPEN_ENDS.md` — authoritative unresolved-work register
- `FUTURE_SCOPE.md` — deferred extensions and future research directions
- `TAXONOMY.MD` — computational-structure taxonomy used by routing
- `SOURCE_OF_TRUTH.md` — documentation authority map
- `RESEARCH_TRACEABILITY.md` — maps research findings to design decisions and evaluation
- `ARCHITECTURE.md` — frozen architecture/specification
- `CONSTITUTION.md` — constitutional change/decision process

## HTTP contract

The HTTP interface now uses server-issued session tokens:

- `POST /v1/session` issues `v1.<id>.<issued_at>.<HMAC-SHA256>` session tokens.
- `POST /v1/respond` requires `session_token`; the old client-chosen `session_id` field is no longer part of the HTTP interface.
- Missing, forged, altered, foreign-secret, or expired session tokens return HTTP **401** with `session_invalid` or `session_expired`, before any request stage runs.
- Unsupported non-text input is refused with `block_reason="unsupported_modality"`; non-JSON request bodies to `/v1/respond` return HTTP **415**.
- The modality refusal boundary does not invoke a tier/model and does not add session risk for the modality problem alone. The text's own Stage 0 verdict remains authoritative.
- `SESSION_SECRET` should be explicitly set in any real deployment. An empty value causes a random per-process secret to be generated with a warning; the current TTL and issuance-rate limits are placeholders.

The HTTP boundary is text-only. The runtime does not claim multimodal support, and it does not claim multilingual support.

## Current sprint status

**Current scope: English only.** OI-077 refuses requests whose letters are mostly non-Latin script at Stage 0, but this detects scripts rather than languages. Latin-script non-English (including Hinglish, Spanish, and French) is not detected by the gate and remains routed through the English-keyword Stage 0/1 rules (OI-076). Multilingual routing and safety coverage are future scope (FS-017); a UI affordance for this scope gate is future scope (FS-018). No architecture change follows from the owner scope decision.

**Sprint 3 — Session context + real cost accounting: COMPLETE.**

**Sprint 4 — Graduated routing + feedforward: IMPLEMENTATION COMPLETE; carry-forwards tracked in `docs/OPEN_ENDS.md`.**

**Sprint 5 — Escalation, validation, governance: CLOSED by owner decision.** Stage 6 validation, bounded repair, live validation/repair wiring, governance, the bias-monitor harness, and the Stage 0 unsupported-script refusal (OI-077) are implemented. OI-065, OI-069, and OI-074 are resolved as documented in `docs/OPEN_ENDS.md`. OI-054 remains open as a no-claim guard: **RAG is NOT complete.**

The Stage 3 planner (`triage/decision.py`) is committed and wired into the live request path in `api/main.py`. The Stage 4 feedforward layer is also committed and integrated, providing templated route/outcome text and a high-cost confirmation gate. The API exposes a `feedforward` response field alongside the confirmation fields where applicable. The small-classifier implementation and retrieval prototype are now also committed; the complete RAG generation path is intentionally not yet implemented.

The latest owner-reported local full-suite run is **816 passed, 1 skipped**. This is an owner-reported result; no independent test run is claimed here.

**Sprint 6 — IN PROGRESS.** Server-issued session identity and the text-only ingress boundary are implemented. CI, the full audit schema, the adversarial suites, and protection for `/.github/workflows/` in both CODEOWNERS copies are not yet complete. Real LLM integration is deferred to Sprint 7. OI-013 is resolved only for client-chosen/forged IDs; OI-078 tracks the residual fresh-session reset path. OI-040 remains open, narrowed to human-identity verification. OI-003 and OI-054 remain open.

Carry-forwards and unresolved work are tracked in `docs/OPEN_ENDS.md`; sprint detail is in `docs/EXECUTION_PLAN.md`.

### Stage 0 unsupported-script refusal (OI-077)

The live API refuses a request at Stage 0 when its letters are mostly non-Latin script. The response is blocked with `block_reason="unsupported_language"`, `tier_used="blocked_stage0"`, and the plain English message: "This version currently supports English only. Please rewrite your request in English." No later stage runs and no tier/cache execution occurs.

When `unsupported_language` is the sole matched Stage 0 reason, the session records the turn with a clean risk input, so the scope refusal adds **no session risk**. If an injection or suspicious pattern also matches, the language-only exemption does not apply and normal blocking/risk charging is preserved. The turn is still recorded and audited as blocked.

This is a **script** check, not language identification. Latin-script non-English such as Hinglish, Spanish, or French is not refused by this gate and remains subject to the English-keyword Stage 0/1 rules. Multilingual routing/safety coverage is future scope (FS-017); a UI affordance for the gate is future scope (FS-018).

Related tests: `tests/guardrails/test_language_gate.py` and `tests/api/test_unsupported_language.py`.

The current `main` branch contains the Sprint 3 session-state/cost/model-selection work, Sprint 4 graduated routing/feedforward, Sprint 5 validation/repair/governance/bias-monitor work, and the Sprint 6 server-issued session identity and text-only ingress boundary. The RAG generation path is intentionally incomplete, and Sprint 6 is not complete.

## Root files
- `README.md` — project overview and repository map
- `requirements.txt` — Python dependencies


## Governance and bias-monitor checks

From the repository root:

```text
python -m policy.governance.change_log check
python -m policy.governance.change_log append --component <file> --decision ACCEPT --decided-by <name> --description "<why>"
python -m triage.bias_monitor
```

The governance check detects whether the latest record matches the governed constitutional files; a matching record is not proof of approval or identity. The bias monitor is a small routing-outcome harness, not a fairness validator.
