# Capstone-Project

This repository contains the Constitutional Runtime capstone implementation: a runtime layer that evaluates requests, applies constitutional/security constraints, considers cheaper computational alternatives, and invokes progressively more capable methods only when required.

## Repository structure

`.github/CODEOWNERS` — GitHub-recognized code-owner enforcement copy

`api/` — the front door
- `main.py` — live Stage 0 → Stage 1 → Stage 2 → Stage 3/5 → Stage 6 → Stage 7 request pipeline
- `settings.py` — app-level settings (API keys, ports, checkpoint signing secret, env variables)

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
- `modality_router.py` — planned minimal text/image/audio routing support (Sprint 6)
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

## Current sprint status

**Current scope: English only.** OI-077 refuses requests whose letters are mostly non-Latin script at Stage 0, but this detects scripts rather than languages. Latin-script non-English (including Hinglish, Spanish, and French) is not detected by the gate and remains routed through the English-keyword Stage 0/1 rules (OI-076). Multilingual routing and safety coverage are future scope (FS-017); a UI affordance for this scope gate is future scope (FS-018). No architecture change follows from the owner scope decision.

**Sprint 3 — Session context + real cost accounting: COMPLETE.**

**Sprint 4 — Graduated routing + feedforward: IMPLEMENTATION COMPLETE; carry-forwards tracked in `docs/OPEN_ENDS.md`.**

**Sprint 5 — Escalation, validation, governance: CLOSURE REVIEW.** Stage 6 validation, bounded repair, non-LLM checks, live validation/repair API wiring, governance, the bias-monitor harness, and the Stage 0 unsupported-script refusal (OI-077) are implemented and committed. Sprint 5 closure is not yet claimed pending review of triggered OIs. Branch-protection/code-owner enforcement on `main` is configured and owner-verified.

The Stage 3 planner (`triage/decision.py`) is committed and wired into the live request path in `api/main.py`. The Stage 4 feedforward layer is also committed and integrated, providing templated route/outcome text and a high-cost confirmation gate. The API exposes a `feedforward` response field alongside the confirmation fields where applicable. The small-classifier implementation and retrieval prototype are now also committed; the complete RAG generation path is intentionally not yet implemented.

The latest owner-reported local full-suite run was **614 passed, 1 skipped**. This is an owner-reported result; no independent test run is claimed here.

Carry-forwards from Sprint 4 include the `CLASSIFICATION` eligibility decision, classifier calibration/evaluation, the complete RAG generation path, empirical resource measurements, and the remaining feedforward/user-study decisions. These are tracked in `docs/OPEN_ENDS.md`; sprint detail is in `docs/EXECUTION_PLAN.md`.

### Stage 0 unsupported-script refusal (OI-077)

The live API refuses a request at Stage 0 when its letters are mostly non-Latin script. The response is blocked with `block_reason="unsupported_language"`, `tier_used="blocked_stage0"`, and the plain English message: "This version currently supports English only. Please rewrite your request in English." No later stage runs and no tier/cache execution occurs.

When `unsupported_language` is the sole matched Stage 0 reason, the session records the turn with a clean risk input, so the scope refusal adds **no session risk**. If an injection or suspicious pattern also matches, the language-only exemption does not apply and normal blocking/risk charging is preserved. The turn is still recorded and audited as blocked.

This is a **script** check, not language identification. Latin-script non-English such as Hinglish, Spanish, or French is not refused by this gate and remains subject to the English-keyword Stage 0/1 rules. Multilingual routing/safety coverage is future scope (FS-017); a UI affordance for the gate is future scope (FS-018).

Related tests: `tests/guardrails/test_language_gate.py` and `tests/api/test_unsupported_language.py`.

The current `main` branch contains the Sprint 3 session-state, cost-estimation, model-selection, and API wiring work, plus the Sprint 4 graduated-routing planner, human checkpoint, feedforward/cost-gate integration, small classifier, and retrieval prototype. Sprint 4 implementation and automated test verification are complete; Stage 6 validation, repair-router logic, and live validation/repair integration are committed and tracked in `docs/OPEN_ENDS.md`.

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
