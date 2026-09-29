# Capstone-Project

This repository contains the Constitutional Runtime capstone implementation: a runtime layer that evaluates requests, applies constitutional/security constraints, considers cheaper computational alternatives, and invokes progressively more capable methods only when required.

## Repository structure

`api/` — the front door
- `main.py` — live Stage 0 → Stage 1 → Stage 2 → Stage 3/5 → Stage 7 request pipeline
- `settings.py` — app-level settings (API keys, ports, env variables)

`config/` — the rulebook, as data
- `constitution.yaml` — policy rules (what's allowed, blocked, flagged)
- `failure_modes.yaml` — what to do if a check times out or errors (block vs. allow)

`cost/` — figures out what things cost
- `calibration/calibration.py` — script to refresh cost numbers from real usage data
- `breakeven.py` — checks whether runtime overhead itself is costing more than it saves
- `estimator.py` — estimates energy/dollar/latency/token cost for a request + tier/model, with explicit assumptions and uncertainty
- `model_registry.py` — model/cost catalog and energy anchors

a`guardrails/` — the security layer
- `adversarial/classifier_attack_suite.py` — test inputs designed to trick the triage classifier
- `adversarial/router_attack_suite.py` — test inputs designed to trick the router into a weaker path
- `injection_screen.py` — catches prompt injection / jailbreak attempts before anything else runs
- `output_filter.py` — checks the final output for unsafe content

`interface/` — what the user sees / where human interaction gates live
- `confidence.py` — shows how reliable a given answer is, so the user knows how much to trust it
- `feedforward.py` — tells the user what's about to happen before it happens (Sprint 4)
- `human_checkpoint.py` — the confirmation/review step for high-stakes requests (Sprint 4+)

`llm/` — talks to the actual AI models
- `gateway.py` — the raw API client (handles auth, retries, request/response format)

`audit/` — keeps a record
- `audit_log.py` — logs every decision made and why
- `metrics.py` — tracks numbers over time (cost saved, escalation rate, etc.)

`policy/` — enforces the rulebook
- `engine.py` — reads `constitution.yaml` and applies the rules
- `schemas.py` — defines the shared data shapes (what a decision or classification looks like)
- `governance/CODEOWNERS` — says who must approve changes to policy files
- `governance/change_log.py` — keeps a version history of policy changes

`session/` — remembers context across a conversation
- `session_state.py` — tracks cumulative risk/cost, turn count, and monotonic constraints across a conversation

`tests/` — automated tests, organized by module/stage as implementation grows

`tiers/` — the actual ways to answer a request, cheapest to priciest
- `cache_lookup.py` — return a previously-saved answer
- `deterministic.py` — rule-based / calculator / lookup answers, no AI involved
- `small_classifier.py` — a small, cheap model for simple categorization tasks
- `rag_small_model.py` — a small model with retrieved reference info to back its answer
- `llm_call.py` — calls the full LLM (via `llm/gateway.py`), with adjustable reasoning depth
- `model_selector.py` — selects among candidate models using capability floors and energy/dollar objectives

`triage/` — decides what kind of request this is and where it should go
- `bias_monitor.py` — checks the router isn't treating some phrasing/languages unfairly (Sprint 5)
- `classifier.py` — figures out what type of request this is (first-pass classifier; full live integration is Sprint 4)
- `decision.py` — the scoring/routing logic for the graduated request ladder
- `modality_router.py` — handles text/image/audio requests (Sprint 6)
- `taxonomy.py` — defines the categories used to classify requests

`validation/` — checks the answer before it's shown to anyone
- `non_llm_checks.py` — cheap, rule-based checks (preferred over using another AI call to check)
- `validator.py` — main validation logic (Sprint 5)

`escalation/`
- `repair_router.py` — decides what happens when a stage fails — retry, escalate to a bigger tier, or hand to a human (Sprint 5)

`docs/` — project control and research documentation
- `EXECUTION_PLAN.md` — sprint status and implementation plan
- `OPEN_ENDS.md` — authoritative unresolved-work register
- `RESEARCH_TRACEABILITY.md` — maps research findings to design decisions and evaluation
- `ARCHITECTURE.md` — frozen architecture/specification
- `CONSTITUTION.md` — constitutional change/decision process

## Current sprint status

**Sprint 3 — Session context + real cost accounting: COMPLETE.**

The current `main` branch contains the Sprint 3 session-state, cost-estimation, model-selection, and API wiring work. Remaining limitations are tracked explicitly in `docs/OPEN_ENDS.md`; Sprint 4 is the next implementation scope.

## Root files
- `README.md` — project overview and repository map
- `requirements.txt` — Python dependencies
