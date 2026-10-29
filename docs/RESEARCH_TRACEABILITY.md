# Research Traceability

Every component in `ARCHITECTURE.md` must trace to at least one entry
below (Development Constitution, Rule 3). This document is the lookup
table that makes that traceability checkable rather than asserted.

---

## The source material

| Paper | What it establishes |
|---|---|
| From Prompts to Power | Per-query energy varies by orders of magnitude by model size/hardware; ships a predictive cost-estimation model — the pattern behind `cost/estimator.py`. |
| Energy Considerations of LLM Inference | Inference (not training) dominates lifecycle energy; the same optimization can help or hurt depending on hardware/software stack — nothing is "free," motivating `cost/breakeven.py`. |
| Quantifying the Energy Consumption and Carbon | Carbon-aware scheduling as a lever; supports treating environmental cost as a first-class, measurable dimension. |
| How Hungry is AI | GPT-5's reasoning-depth modes span a 7x energy range on the same query; documents the Jevons Paradox (efficiency gains increase total usage rather than reducing it) — the core justification for "cheapest adequate," not just "more efficient." |
| A Review of Prominent Paradigms for LLM-Based Agents | Names "is this too simple to decompose" as an unresolved gap in existing agent frameworks — the literal justification for `triage/decision.py`'s necessity check. Also the source of the Policy/Planning/Tools/Retrieval/Feedback decomposition inside the AI execution branch. |
| AI Risk Management Framework (NIST GenAI Profile) | Source of the risk category taxonomy (`RiskCategory` enum), the Govern/Map/Measure/Manage structure behind `policy/`, and the "automation bias" risk that justifies `interface/human_checkpoint.py`. GV-1.5-002 recommends documented after-action reviews for incidents; GV-1.5-003 calls for a retention policy for TEVV history; GV-1.6-003 highlights personal, privileged, proprietary, and sensitive data considerations. These support governed evidence retention, but do not prescribe HMAC, per-record salts, or a particular audit schema. |
| Jailbreak Attacks and Defenses Against LLMs | Attacks are cheap and model-knowledge-agnostic and evolving faster than defenses — justifies filtering upstream (Stage 0) rather than relying on model alignment alone, and justifies adversarially testing the *router/classifier*, not just the LLM. |
| Prompt Injection (OWASP LLM Top 10) | The supplied source contains only a truncated LLM10:2025 blurb about "Unbounded Consumption"; it also flags cross-modal injection. Detailed LLM10 control recommendations are external to the supplied research set and are not treated as supplied-paper support. |
| Sensitive Information Disclosure (OWASP) | Applies regardless of which tier answers — justifies the policy gate covering the deterministic/non-AI branch, not just the AI branch. |
| The Impact of Gen AI on Critical Thinking | Confidence in AI output (not accuracy) predicts reduced scrutiny; introduces "stewardship" as the target human role — justifies `interface/feedforward.py` and `human_checkpoint.py`. |
| The Metacognitive Demands and Opportunities of Generative AI | "Processing fluency" as the mechanism (fast, fluent output inflates confidence independent of correctness); proposes "feedforward" as the concrete mitigation — direct source of Stage 4. |
| Practices, Norms and Implications of Gen AI in Education | Real-world fieldwork showing people already informally weigh task importance, verification cost, and domain expertise — the heuristics behind `triage/decision.py`'s scoring inputs are not invented, they're observed and formalized. |

---

## Component → paper mapping

| Component | Traces to |
|---|---|
| `session/identity.py`, `api/settings.py` | [PROJECT] OI-013/OI-078 define the server-issued session identity boundary and its residual limits. [JUDGMENT] HMAC-SHA256 token format, token TTL, issuance-rate limits, per-process in-memory limiter, client-key derivation from peer address, and fail-closed issuance/verification behavior are implementation choices.  |
| `guardrails/injection_screen.py` | [SPEC] Stage 0 #5 requires a deterministic/no-AI ingress constraint and the Stage 0 verdict set remains clean/suspicious/blocked. [PROJECT] OI-077 implements an English-scope refusal for requests whose letters are mostly non-Latin script; injection/block patterns run first, the language-only case runs no later stage, and the API records it without session-risk charging. [JUDGMENT] the ≥3 non-Latin-letter threshold, strictly-more-than-half majority threshold, and sole-reason risk exemption. This detects scripts, not languages; Latin-script non-English remains routed under the English-keyword rules (OI-076/FS-017).
| `guardrails/match_view.py` and CP-002 Part A | [PROJECT] CP-002 defines raw-text-derived matching views used only by Stage 0/1 gates; the normalization-v1 output, classifier/model input, cache key, confirmation binding, audit digest, and golden test remain unchanged. [RESEARCH] Unicode normalization (NFKC) and Unicode general-category data inform the normalization vocabulary, but the supplied project PDFs do **not** specify the matching tables or thresholds. [JUDGMENT] the pinned character tables, hand-curated 25-entry confusable-folding list, invisible-character threshold of 2, emoji joiner limit of 3, and subdivision-flag tag length range of 2–8. The supplied *Jailbreak Attacks and Defenses Against LLMs* and truncated OWASP Prompt Injection source support the threat framing—obfuscation/evasion and upstream screening—not these particular values. Evidence is a hand-written 70-item Claude corpus, not real traffic; see OI-080–OI-089. This is not evidence of general obfuscation robustness.
| `guardrails/adversarial/` | [RESEARCH] Jailbreak Attacks and Defenses supports testing the upstream screen and routing components rather than assuming defenses generalize. [PROJECT] Sprint 6 adds whole-pipeline and session-rotation suites with strict xfails for currently succeeding attacks/accepted limits. CP-002 Part A reports 20 formerly-xfailed cases now pass (F-01 ×10, F-02 ×7, F-03 ×2, F-05 ×1); 12 legacy xfails remain (9 in `pipeline_attack_suite.py`, 3 in `session_rotation_attack_suite.py`), plus 8 new residual-limit xfails (7 in `guardrails/adversarial/matching_view_attack_suite.py`, 1 in `tests/guardrails/test_invisible_signal.py`). The merged implementation CI run on `8d29c147767f71512fbb61af9f5e992385bcad43` passed with 1,439 passed, 20 xfailed, 1 warning (run [#39316274092](https://github.com/alaukikk/Constitutional-Runtime/actions/runs/39316274092)). The owner-reported local/sandbox run reported 1,438 passed; it is separate from and superseded for merge evidence by the CI result. The N-01–N-06 reports record 7 changed items, each justified, and 14 pasted samples; the 70-item benign corpus was hand-written by Claude, not real traffic. R-01 used 320 seeded mutations; the monotonic-superset property held and at least 60 mutations gained a match. These results characterize only the tested corpus and transformations and do not demonstrate injection robustness. See OI-080–OI-090. |
| `policy/engine.py`, `config/constitution.yaml` | NIST AI RMF GenAI Profile |
| `config/failure_modes.yaml` | NIST AI RMF (Environmental Impacts + Human-AI Configuration sections implicitly require explicit failure semantics) |
| `policy/governance/` | [RESEARCH] NIST AI RMF GenAI Profile (Govern function supports defined responsibilities, governance processes, and documentation). [PROJECT] OI-067 implements CODEOWNERS plus a machine-readable constitutional-file integrity log. [JUDGMENT] SHA-256 line-ending normalization, record schema, and the boundary that a matching record does not imply approval are implementation choices. |
| `cost/estimator.py`, `model_registry.py` | From Prompts to Power; How Hungry is AI |
| `cost/breakeven.py` | Energy Considerations of LLM Inference (optimizations aren't free); How Hungry is AI (Jevons Paradox applied recursively to the runtime itself). [PROJECT] Implemented (Sprint 7–8); it covers latency, token and retrieval-ceiling analysis only, with no energy or dollar figures (OI-005). |
| `llm/gateway.py` | [PROJECT] In-house LLM gateway (`stub`, `anthropic`, `openai_compat`) built for the Sprint 7–8 experiment; see OI-006, OI-010, OI-092. [JUDGMENT] no retries, no silent fallback, static error codes, pacing and output-token defaults. |
| `evaluation/*` | [PROJECT] Golden set v1 (106 draft items), offline runner, review tooling and end-to-end runner for the Sprint 7–8 experiment; see OI-011, OI-091, OI-093, OI-094. [JUDGMENT] labels, containment-based scoring and split assignment are draft judgments, not research findings. |
| `triage/decision.py` | [SPEC] Stage 3 #1, #4, #7, #9, #10. [RESEARCH] How Hungry is AI §7, p.11 (reasoning depth as a cost dial). The existing LLM-Agents and Education citations are "per traceability doc, not re-verified". [JUDGMENT] 0.4 confidence floor (OI-029), 0.7 capability floor (OI-033). |
| `triage/bias_monitor.py` | [RESEARCH] NIST AI RMF GenAI Profile supports measuring and documenting bias/fairness and recognizing subgroup/language disparities. [PROJECT] OI-068 implements a small paired-request routing-outcome harness. [JUDGMENT] hand-written pair construction, English baseline, comparison metrics, and the conclusion that the small harness cannot establish fairness. See OI-056 and FS-017. |
| `triage/modality_router.py` | [SPEC] ARCHITECTURE Stage 5 #6 requires safe handling before execution. [RESEARCH] The supplied OWASP Prompt Injection source flags cross-modal injection as a multimodal risk. [PROJECT] OI-079 chooses refusal rather than multimodal defense. [JUDGMENT] the supported-field list, empty-value tolerance, data-URI pattern, scan limit, and fail-closed treatment of modality-check errors. This does not claim complete detection of all smuggling methods or multimodal support. |
| `interface/feedforward.py` | [SPEC] Stage 4 (#3 hard gate, #7 failure behavior) and Stage 3 #6 (omit classifier internals). The existing Metacognitive Demands citation is "per traceability doc, not re-verified". [JUDGMENT] cost-gate limits (OI-045), `HIGH_STAKES` not a gate (OI-046), fail-open/fail-closed split (OI-050). |
| `interface/confidence.py` | Impact of Gen AI on Critical Thinking (confidence ≠ accuracy finding) |
| `interface/human_checkpoint.py` | [SPEC] Stage 1 #10, Stage 7 #6. The existing NIST automation-bias and Critical Thinking citations are "per traceability doc, not re-verified". [JUDGMENT] token mechanics (HMAC-SHA256, 5-minute TTL, single use) come from general security practice, not the research set; once-only risk charging (OI-043); identity gap (OI-040). |
| `tiers/spam_seed_synthetic.py` | [PROJECT] TAXONOMY 2.8. [JUDGMENT] content. Synthetic, English-only, not evidence (OI-051, OI-057). |
| `tiers/cache_lookup.py` | [SPEC] core principle and Stage 3 #4 (exact match only, never bypasses the screen). No research claim. |
| `tiers/deterministic.py` | [SPEC] Stage 3 #1 (cheapest tier that can reliably handle it). [PROJECT] TAXONOMY 2.1, 2.2; Constitution Rule 1. No research claim. |
| `tiers/small_classifier.py` | [SPEC] Stage 3 #4, #10. [PROJECT] TAXONOMY 2.8. [RESEARCH] Energy Considerations of LLM Inference, p.3 of the supplied file (classification involves minimal generation) and p.4 (decoding dominates energy except for short-generation tasks like classification); From Prompts to Power §VI, p.11 (judge performance and energy together). [JUDGMENT] TF-IDF + logistic regression, hyperparameters, thresholds (OI-052). |
| `tiers/retrieval.py` | [PROJECT] TAXONOMY 2.1, 2.13. [RESEARCH] Agents review §4.2, p.5 (in passive RAG, retrieval supplies information the model uses to generate its response). [JUDGMENT] TF-IDF and cosine similarity, chunking, `min_score`, `docs/` as a prototype corpus (OI-054). |
| `tiers/rag_small_model.py` | [PROJECT] TAXONOMY 2.13. [RESEARCH] Agents review §4.2, p.5. Stub: generation is blocked by OI-006. |
| `audit/metrics.py` | [RESEARCH] Prompts to Power §VI, p.11; Energy Considerations p.1 (idealized settings miss real workloads, so measure real ones). [PROJECT] evaluation framework above. [JUDGMENT] metric definitions. Energy figures are estimates (OI-055). |
| `tiers/model_selector.py` | [RESEARCH] How Hungry is AI; From Prompts to Power (resource-aware model selection and model-dependent energy variation). |
| `triage/classifier.py`, `triage/taxonomy.py` | Project taxonomy/specification; these define routing categories and are not claimed as externally validated taxonomies. |
| `guardrails/output_filter.py` | Sensitive Information Disclosure (OWASP) and the frozen architecture's requirement that security/validation boundaries apply across execution branches. |
| `api/main.py` | Frozen architecture/specification and project integration work; no single paper is claimed as direct evidence for the API wiring itself. |
| `session/session_state.py` | Identified during architecture stress-test, not from a single paper — a general multi-turn systems gap the papers don't directly cover |
| `escalation/repair_router.py` | [SPEC] Stage 5 #7/#10 and Stage 6 #10 define repair-router invocation/decision space. [RESEARCH] The supplied Prompt Injection source provides only the LLM10:2025 blurb-level identification of Unbounded Consumption; the detailed OWASP control recommendations are external to the supplied research set. [JUDGMENT] bounded retry/skip/withhold rules (see OI-069) are project decisions, not claims established by the supplied research. |
| `validation/non_llm_checks.py` | [SPEC] Stage 6 #4 preference for non-LLM checks. [RESEARCH] NIST GenAI Profile MG-2.2-001 supports comparing/reviewing generated outputs against predefined guidelines; MG-2.2-005 supports output analysis for harmful content. |
| `validation/validator.py` | [SPEC] Stage 6 #5/#7 define validator allowance and failure semantics; Stage 6 #10 defines repair-router escalation after validation failure. [PROJECT] Current validator implementation uses non-LLM checks and policy-defined failure semantics, with classifier `HIGH_STAKES` excluded by OI-046/061. |
| `audit/audit_log.py` | [SPEC] Stage 7 audit schema target; Stage 5 #8 (actual vs. estimated cost). [PROJECT] OI-058, OI-071. |

---

## Sprint 6 adversarial evidence (current-behavior measurement)

The pre-CP-002 merged whole-pipeline/session suite reported 1,029 passed, 32 xfailed, and 1 warning on main commit `20bef7523433630191e4913d45ef17648201f7c7` (CI run #38878440684, 2026-10-16). This is historical evidence, not the CP-002 Part A result. The owner-reported local/sandbox run reported 1,438 passed. The merged implementation CI result is 1,439 passed, 20 xfailed, 1 warning on commit `8d29c147767f71512fbb61af9f5e992385bcad43` (run [#39316274092](https://github.com/alaukikk/Constitutional-Runtime/actions/runs/39316274092)). The owner reported that `pytest (Python 3.11)` was added as a required status check on `main` on 2026-10-20; that repository-settings change has not been independently verified here. Verify the active `protect-main` ruleset and enforcement on a pull request before treating CI as a confirmed merge gate.

For CP-002 Part A, 20 formerly-xfailed cases are now passing: F-01 ×10, F-02 ×7, F-03 ×2, and F-05 ×1. The 12 legacy xfails remaining are 9 in `pipeline_attack_suite.py` and 3 in `session_rotation_attack_suite.py`; 8 new residual-limit xfails remain (7 in `guardrails/adversarial/matching_view_attack_suite.py`, 1 in `tests/guardrails/test_invisible_signal.py`). Thus 12 + 8 = 20 xfailed, matching the merged CI result. N-01–N-06 evidence is stored in `tests/guardrails/data/matching_view_new_matches.json` (7 changed items, each justified) and `matching_view_pasted_report.json` (14 pasted samples). The 70-item benign corpus is hand-written by Claude, not real traffic. R-01 covers 320 seeded mutations; the monotonic-superset property held and at least 60 mutations gained a match. These are bounded test results, not proof of broad injection robustness or generalization to unseen attacks. N-07 is not applicable because `mixed_script_token` is deferred under FS-025. OI-080 is partially resolved (F-04 open); OI-081 is resolved for tested whitespace, hyphen, and apostrophe handling only; OI-082 remains the pattern-only limit; OI-086/OI-087/OI-089/OI-090 are provisional defaults and may only be cited as limitations, not evidence of a property; OI-088 is a known defect, not a provisional default; OI-078/OI-083/OI-084/OI-085 and OI-086–OI-090 remain open.

## Sprint 7–8 first diagnostic results (2026-10-29)

**[PROJECT]** The first end-to-end and breakeven runs on the 106-item draft golden set (one provider, one machine, one run) measured negligible runtime overhead (mean 1.737 ms) and a routing-attributable token saving of 8.0% (1,829 of 22,897 baseline tokens); the all-in 15.9% difference mixes in model choice (OI-093). These are diagnostic and draft-labelled; they support no energy or dollar claim and do not support "considerable savings" (OI-097). The owner's direction to expand non-AI coverage incrementally and accept added latency (OI-098) is a design direction, not a research finding. **[RESEARCH]** The metacognition paper (as cited in it; original studies not re-verified) reports processing-fluency effects, that faster answers can be judged more correct, and that slower interfaces may aid reflection. This is hypothesis-level motivation for preferring non-AI methods at a latency cost; it supports concern about AI fluency, not avoiding AI per se, and the project does not claim it as evidence.

## Sprint 7–8 provisional-default reporting

The Sprint 7–8 report must include a table titled **Provisional defaults in force**, with the live OI-086–OI-090 rows, default, revisit trigger, evidence gathered during Sprints 7–8, and outcome (kept / changed / still open). OI-088 must remain visible in that table but be labelled as an accepted defect/limit, not a provisional default. Provisional defaults are stated limitations only, not evidence that a property holds. Reopen Stage 0/1 hardening only if shadow-mode or red-team evidence shows false positives that distort evaluation or a specific bypass material to a claim being made; otherwise retain residuals as limits for post-execution refinement.

## Evaluation framework

The capstone should measure across five dimensions, not just "did we
use an LLM." Each dimension maps to specific components:

| Dimension | Measured by | Backing components |
|---|---|---|
| **Resource efficiency** | tokens, latency, estimated energy, dollar cost, model calls, reasoning depth | `cost/estimator.py`, `model_registry.py` |
| **Decision quality** | task success, correctness, validation failure rate, escalation frequency | `validation/`, `escalation/repair_router.py` |
| **Constitutional compliance** | policy violations prevented, injection attempts caught, unsafe routes prevented | `guardrails/`, `policy/` |
| **Human agency** | feedforward visibility, human overrides, unnecessary automation avoided, user acceptance/rejection rate | `interface/feedforward.py`, `human_checkpoint.py` |
| **Runtime overhead** | cost of the runtime's own gating machinery, latency added, energy consumed by the runtime itself | `cost/breakeven.py` |

The central experimental question the capstone should be able to
answer:

> **At what workload characteristics does the constitutional runtime
> produce net resource savings after accounting for its own
> computational overhead?**

This is not a rhetorical framing — `cost/breakeven.py` exists
specifically to produce a real, measured answer to this question.

---

## Validation, repair, and withholding — research basis

### Validation

The NIST GenAI Profile provides direct support for treating generated-output review as a risk-control activity. **MG-2.2-001** calls for comparing GAI outputs against predefined risk tolerances, guidelines, and principles and reviewing/testing generated content against them. **MG-2.2-005** calls for due diligence in analyzing GAI output for harmful content and related risks. These support the existence and purpose of Stage 6, but do not establish that the current non-LLM checks prove factual correctness.

### Human oversight and feedback

NIST **GV-3.2-003/004** addresses acceptable-use/refusal policies and user feedback/recourse, while **MS-3.3-002/005** addresses studying end-user interaction and recording structured feedback. These support future human-review/recourse and feedback extensions; they do not imply that the current runtime has a human-review workflow.

The supplied *A Review of Prominent Paradigms for LLM-Based Agents* discusses evaluator/feedback workflows in agent systems. This supports the general evaluate → feedback/repair pattern used by the repair router, but not the project's exact retry limits or terminal state.

### Why WITHHOLD is the current terminal state

The current OI-066 decision is a **project/architecture decision informed by research, not a direct prescription from a paper**. NIST MG-2.2-001 supports comparing and reviewing generated outputs against predefined risk tolerances, guidelines, and principles. The project's decision to withhold an output when it fails validation, in the absence of a human-review/release workflow, is its own implementation/architecture choice. The current system has no implemented human-review/release workflow, so WITHHOLD is the honest terminal state rather than implying human approval that did not occur.

The supplied energy/inference sources establish that inference resource use varies substantially with workload, model, hardware, and software conditions. That supports bounded repair as a resource-efficiency concern, but does not prove the exact one-escalation rule.

The supplied OWASP source names LLM10:2025 Unbounded Consumption, but its text is truncated, so it supports only the existence of the category; the nature of the risk and its recommended controls are external. The energy sources support bounded resource use as a concern. Neither establishes the project's exact repair-router rules.

Accordingly:
- **[RESEARCH]** supports validation as a control, human feedback/recourse as a useful future capability, and bounded resource use as a concern.
- **[PROJECT]** covers the exact WITHHOLD terminal behavior (OI-066), as an owner/project decision informed by the research. **[JUDGMENT]** covers the repair-router details tracked under OI-069.


## Current scope and deferred language coverage

**[PROJECT]** The owner has scoped the current runtime to English only. `ARCHITECTURE.md` is unchanged. Stage 3 #12 names languages, but multilingual support is deferred by owner decision rather than treated as satisfied. OI-068's Hindi/Hinglish measurements are diagnostic evidence of current English-keyword routing limitations, not evidence of multilingual support or Hindi/Hinglish quality. Multilingual routing and safety coverage are tracked as FS-017.
