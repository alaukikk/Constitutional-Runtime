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
| Prompt Injection (OWASP LLM Top 10) | "Unbounded Consumption" (LLM10:2025) is the vulnerability the entire tiered-execution design exists to close. Also flags cross-modal injection — justifies `triage/modality_router.py`. |
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
| `triage/decision.py` | LLM-Agents Review (necessity gap); Practices/Norms in Education (real heuristics); How Hungry is AI (reasoning depth as continuous dial) |
| `triage/bias_monitor.py` | NIST AI RMF (Harmful Bias and Homogenization) |
| `triage/modality_router.py` | Prompt Injection / OWASP (cross-modal injection) |
| `interface/feedforward.py` | Metacognitive Demands paper (direct source of the design pattern) |
| `interface/confidence.py` | Impact of Gen AI on Critical Thinking (confidence ≠ accuracy finding) |
| `interface/human_checkpoint.py` | NIST AI RMF (automation bias); Critical Thinking paper (stewardship) |
| `tiers/small_classifier.py` | Project taxonomy (statistical classification → classical/specialized ML); Energy Considerations of LLM Inference and Efficiency Optimizations (lightweight/discriminative inference as a lower-generation workload). The synthetic seed itself is project/test data, not research evidence. |
| `tiers/retrieval.py` | A Review of Prominent Paradigms for LLM-Based Agents (retrieval as a distinct execution component); implementation/evaluation boundary is project design. |
| `tiers/rag_small_model.py` | A Review of Prominent Paradigms for LLM-Based Agents (retrieval + generation decomposition); the current generation stub is an implementation limitation, not a research claim. |
| `audit/metrics.py` | Evaluation framework in this document; retrieval/classifier metric helpers are measurement infrastructure rather than direct findings from a paper. |
| `tiers/model_selector.py` | How Hungry is AI; From Prompts to Power (resource-aware model selection and model-dependent energy variation). |
| `triage/classifier.py`, `triage/taxonomy.py` | Project taxonomy/specification; these define routing categories and are not claimed as externally validated taxonomies. |
| `guardrails/output_filter.py` | Sensitive Information Disclosure (OWASP) and the frozen architecture's requirement that security/validation boundaries apply across execution branches. |
| `api/main.py` | Frozen architecture/specification and project integration work; no single paper is claimed as direct evidence for the API wiring itself. |
| `session/session_state.py` | Identified during architecture stress-test, not from a single paper — a general multi-turn systems gap the papers don't directly cover |
| `escalation/repair_router.py` | Synthesized from ChatGPT's original diagram + generalized during merge |
| `validation/non_llm_checks.py` | Architecture-review gap ("who validates the validator") |
| `audit/audit_log.py` | NIST AI RMF (incident disclosure named as a priority consideration) |

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
