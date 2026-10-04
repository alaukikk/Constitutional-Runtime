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
| AI Risk Management Framework (NIST GenAI Profile) | Source of the risk category taxonomy (`RiskCategory` enum), the Govern/Map/Measure/Manage structure behind `policy/`, and the "automation bias" risk that justifies `interface/human_checkpoint.py`. |
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
| `guardrails/injection_screen.py` | Jailbreak Attacks and Defenses |
| `guardrails/adversarial/` | Jailbreak Attacks and Defenses (attacks evolve faster than defenses — router/classifier need the same scrutiny) |
| `policy/engine.py`, `config/constitution.yaml` | NIST AI RMF GenAI Profile |
| `config/failure_modes.yaml` | NIST AI RMF (Environmental Impacts + Human-AI Configuration sections implicitly require explicit failure semantics) |
| `policy/governance/` | NIST AI RMF (Govern function) |
| `cost/estimator.py`, `model_registry.py` | From Prompts to Power; How Hungry is AI |
| `cost/breakeven.py` | Energy Considerations of LLM Inference (optimizations aren't free); How Hungry is AI (Jevons Paradox applied recursively to the runtime itself) |
| `triage/decision.py` | [SPEC] Stage 3 #1, #4, #7, #9, #10. [RESEARCH] How Hungry is AI §7, p.11 (reasoning depth as a cost dial). The existing LLM-Agents and Education citations are "per traceability doc, not re-verified". [JUDGMENT] 0.4 confidence floor (OI-029), 0.7 capability floor (OI-033). |
| `triage/bias_monitor.py` | NIST AI RMF (Harmful Bias and Homogenization) |
| `triage/modality_router.py` | Prompt Injection / OWASP (cross-modal injection) |
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

OWASP **LLM10:2025 Unbounded Consumption** identifies excessive/uncontrolled inference as a resource and cost risk and LLM10 is identified as a risk (blurb only), control recommendations are external, and bounded resource use is supported by the energy sources instead. This supports treating repair bounds as a security/resource concern. It does **not** establish the project's exact repair-router rules.

Accordingly:
- **[RESEARCH]** supports validation as a control, human feedback/recourse as a useful future capability, and bounded resource use as a concern.
- **[JUDGMENT]** covers the exact WITHHOLD terminal behavior and the repair-router details tracked under OI-069.
