# Future Scope

This document records improvements, extensions, and research directions that are intentionally
outside the current execution plan. It is a forward-looking registry, not an extension of the
frozen architecture.

The current execution plan remains the implementation authority for the capstone's active scope.
Items in this document must not be treated as implemented, required for the current sprint, or
implicitly approved architectural changes.

When the current execution plan has been completed and the core hypothesis has been evaluated,
this document can be used to select the next phase of work. Any future change that alters the
frozen architecture, stage structure, shared interfaces, security boundaries, or constitution
must still follow the governance process in `CONSTITUTION.md`.

---

## Purpose

The constitutional runtime is intentionally being developed in bounded stages. This prevents
future improvements from expanding the active implementation surface before the core hypothesis
has been measured:

> Can a constitutional runtime reliably select the cheapest adequate method for a request,
> while reducing unnecessary AI use, preserving safety and human agency, and accounting for
> the runtime's own overhead?

This document captures useful directions that should **not** be lost merely because they are
outside the current capstone execution plan.

---

## How to use this document

### Status

Future-scope entries are intentionally not part of `OPEN_ENDS.md` unless they become an active
decision, defect, or verification requirement.

Suggested lifecycle:

1. **Future** — recorded as a possible extension.
2. **Candidate** — selected for consideration after the current execution plan.
3. **Approved** — project owner has explicitly chosen it for a future phase.
4. **Active** — moved into a concrete execution plan/sprint.
5. **Completed** — implemented and verified.
6. **Dropped** — deliberately rejected or superseded.

Moving an item into active implementation does not by itself authorize an architecture change.
The normal governance/change-proposal process still applies where required.

### Scope boundary

Future scope must not be used to excuse a missing requirement from the current execution plan.
Conversely, an item being listed here does not create a commitment to implement it.

---

# Future Scope Registry

## FS-001 — Human Review and Recourse Workflow

**Priority:** High  
**Status:** Future  
**Related:** OI-066, Stage 4, Stage 7

### Motivation

The current runtime can withhold an output when validation fails and no safe repair remains,
but it does not contain a complete human-review/release workflow.

A future implementation could provide an explicit review queue in which a human can inspect:

- the original request;
- policy and security outcomes;
- selected tier/model;
- generated output;
- validation failures;
- repair attempts;
- resource/cost information; and
- relevant audit history.

The human could then approve, edit, reject, or otherwise disposition the result.

### Why this is future scope

The current system must not claim that a human reviewed an output when no such workflow exists.
The current `WITHHOLD` terminal state provides a safe extension point for this capability.

### Expected benefit

Adds genuine human oversight and recourse rather than merely exposing a machine-generated
"needs review" label.

---

## FS-002 — Structured User Feedback on Runtime Decisions

**Priority:** High  
**Status:** Future  
**Related:** FS-001, OI-059, Stage 4

Capture structured feedback about whether users considered the runtime's intervention useful,
unnecessary, confusing, or incorrect.

Potential signals include:

- accepted/rejected feedforward;
- cancellation reason;
- disagreement with selected tier;
- feedback on withheld outputs;
- human override decisions; and
- perceived usefulness of explanations.

### Expected benefit

Allows the project to evaluate whether the runtime improves human agency in practice rather than
assuming that a theoretically transparent interface does so.

---

## FS-003 — Empirical Calibration

**Priority:** High  
**Status:** Future  
**Related:** OI-018, OI-029, OI-052, OI-062, OI-057

### In current scope

Sprints 5–8 already require calibration of routing and validation thresholds against the golden
set and empirical evaluation data. This includes the existing OI-018, OI-029, OI-052, OI-057,
and OI-062 triggers.

### Future extension

After the current evaluation, extend calibration to broader workloads and longer-running
deployments, including drift monitoring and recalibration policies for routing confidence,
validation confidence, repair success, and false-escalation/false-withholding rates.

### Expected benefit

Turns provisional operating points into empirically defensible and maintainable thresholds
without incorrectly treating the current calibration work as deferred future scope.

## FS-004 — Independent Classifier Data and Fairness Evaluation

**Priority:** High  
**Status:** Future  
**Related:** OI-051, OI-056, OI-057, OI-068

### In current scope

Sprint 5 includes the first small routing-outcome comparison harness. The current runtime scope is
English only by owner decision. Sprints 7–8 still require independently labeled evaluation data
before empirical classifier claims.

### Future extension

Extend beyond the initial English evaluation to independently reviewed, representative datasets,
including multilingual and subgroup coverage, repeated measurements, subgroup analysis, and
longitudinal monitoring of routing accuracy, abstention, escalation frequency, selected tier,
resource use, and downstream validation outcomes.

### Expected benefit

Tests whether the efficiency layer introduces systematic disparities beyond the initial
capstone evaluation.

## FS-017 — Multilingual Routing and Safety Coverage

**Priority:** Medium  
**Status:** Future  
**Related:** OI-056, OI-076, FS-004, Stage 3 #12

### Current scope boundary

The owner has explicitly scoped the current runtime to English. No architecture change follows
from that decision, and Stage 3 #12's language requirement is deferred rather than treated as
satisfied.

### Future extension

Extend routing and safety coverage beyond English, including:

- classifier vocabulary and language coverage;
- Stage 0 patterns and Stage 1 keyword rules;
- estimator/tokenization behavior for non-ASCII text;
- independently labelled and native-speaker-reviewed data;
- multilingual routing evaluation; and
- multilingual safety evaluation.

This extends FS-004's evaluation direction rather than replacing it. The OI-068 Hindi/Hinglish
measurements are diagnostic evidence of current limitations, not evidence of multilingual quality.

### Expected benefit

Establish whether the constitutional runtime can preserve its routing, safety, and resource-aware
properties across languages instead of assuming English-oriented controls transfer unchanged.

---

## FS-005 — Resource-Aware Repair Selection

**Priority:** High  
**Status:** Future  
**Related:** OI-030, OI-045, OI-055, OI-065

The current repair mechanism is intentionally bounded. A future version could make repair selection
more resource-aware by estimating the expected benefit of each candidate repair against its
marginal resource cost.

Potential factors:

- estimated energy;
- dollar cost;
- latency;
- probability of successful validation;
- capability improvement;
- accumulated request/session cost; and
- uncertainty in the estimates.

The objective would be to select the repair with the best expected outcome rather than simply
moving upward to the next available tier.

### Constraint

This should improve bounded repair; it should not become an excuse for unbounded retrying.

---

## FS-006 — Validation and Repair Outcome Learning

**Priority:** Medium  
**Status:** Future  
**Related:** OI-062, OI-065, OI-068, OI-069

Use accumulated audit data to study which requests, tiers, validators, and repair strategies
actually succeed.

Potential uses:

- calibrating routing confidence;
- estimating repair success;
- identifying recurring validation failures;
- improving cost/energy estimates;
- detecting systematic failure patterns; and
- identifying opportunities for deterministic handling.

Any adaptive mechanism should remain governed and auditable. Automatic modification of
constitutional policy or security boundaries must not be introduced merely because historical
data suggests a change.

---

## FS-007 — Compound-Request Decomposition

**Priority:** Medium  
**Status:** Future  
**Related:** OI-027

Extend the runtime from a single-request routing decision to decomposition of compound requests
into independently routable subproblems.

Example conceptual flow:

`request -> subproblem A + subproblem B + subproblem C -> independent routing -> recombination`

This should only be pursued if evaluation shows that compound requests materially limit the
single-request model.

### Expected benefit

Allows deterministic or low-cost handling of individual portions of a request even when another
portion genuinely requires an AI tier.

### Constraint

Decomposition must preserve Stage 0/1 security and policy boundaries for every resulting
subproblem and must not silently weaken the current request-level guarantees.

---

## FS-008 — Real Multi-Provider / Model Integration

**Priority:** Medium  
**Status:** Future  
**Related:** OI-006, OI-010

Replace the current/staged model stubs with real provider integrations after the core hypothesis
has been validated on a sufficiently small model set.

Potential extensions include:

- multiple providers;
- multiple model families;
- real reasoning-depth controls;
- provider-specific latency/energy measurements; and
- empirical capability catalogs.

### Expected benefit

Makes model selection and resource comparisons representative of real deployments.

---

## FS-009 — Empirical Energy and Cost Measurement

**Priority:** High  
**Status:** Future  
**Related:** OI-005, OI-036, OI-045, OI-055

### In current scope

Sprints 7–8 already require real workload measurements and comparison against an always-direct
LLM baseline. OI-005, OI-036, OI-045, and OI-055 track the current empirical-calibration boundary.

### Future extension

Extend measurement across additional models, hardware/software stacks, workloads, modalities,
and deployment conditions. Measure uncertainty and error in energy, dollar, latency, token, and
runtime-overhead estimates rather than treating one deployment's measurements as universal.

### Expected benefit

Tests the resource-efficiency claim across a broader operating envelope.

## FS-010 — Runtime Breakeven and Overhead Optimization

**Priority:** High  
**Status:** Future  
**Related:** OI-005, OI-030, OI-055, Sprints 7–8

### In current scope

Sprints 7–8 already require running `cost/breakeven.py` and answering the central question of
whether runtime overhead is outweighed by avoided AI inference cost.

### Future extension

Extend breakeven analysis to additional workload distributions, cache-hit rates, validation and
repair overheads, deployment configurations, and optimization strategies. Study how the runtime
can reduce its own overhead without weakening constitutional controls.

### Expected benefit

Identifies the operating conditions where the runtime remains net-beneficial and where it should
decline to intervene.

## FS-011 — Expanded Modality Routing

**Priority:** Medium  
**Status:** Future  
**Related:** ARCHITECTURE Stage 5 #6; EXECUTION_PLAN Sprint 6

### In current scope

Sprint 6 includes the minimal `triage/modality_router.py` implementation and the associated
adversarial-testing work. This future entry does not defer that planned Sprint 6 deliverable.

### Future extension

Extend the routing/security model beyond text to image, audio, and other modalities.

The extension should independently consider:

- modality-specific attack surfaces;
- modality-specific resource costs;
- modality-specific deterministic alternatives;
- cross-modal prompt injection;
- modality-specific validation; and
- whether one modality can safely be trusted based on another.

This should not assume that controls designed for text automatically transfer unchanged to other
modalities.

---

## FS-012 — Production-Grade Session and State Infrastructure

**Priority:** Medium  
**Status:** Future  
**Related:** OI-013, OI-020, OI-021, OI-040, OI-041

Replace the current development-oriented session infrastructure with production-grade state
management where deployment requirements justify it.

Potential work includes:

- server-issued/signed session identity;
- upstream authentication binding;
- distributed storage;
- atomic multi-instance updates;
- bounded state retention;
- safe eviction; and
- recovery semantics that cannot silently reset security-relevant context.

This is primarily an engineering hardening direction rather than a core research contribution.

---

## FS-013 — Governance Automation and Change Traceability

**Priority:** Medium  
**Status:** Future  
**Related:** OI-067, OI-075, `policy/governance/`

### In current scope

Sprint 5 now includes the initial governance slice: canonical and GitHub-recognized CODEOWNERS,
a machine-readable constitutional-file change log, SHA-256 integrity records, and an integrity
test. Owner verification of branch-protection enforcement is tracked separately under OI-075.

### Future extension

Complete and generalize the governance machinery so that changes to constitutional rules, policy
schemas, routing rules, and other protected components are automatically attributable and
reviewable.

Potential capabilities:

- mandatory change records;
- protected ownership rules;
- architecture-change checks;
- policy/schema compatibility checks;
- machine-readable decision provenance; and
- automated detection of changes that require owner approval.

### Expected benefit

Makes the "constitutional" property enforceable by the development/runtime process rather than
relying primarily on documentation discipline.

---

## FS-014 — Stronger Validator Diversity

**Priority:** Medium  
**Status:** Future  
**Related:** OI-060, OI-061, OI-062

Expand validation beyond the current non-LLM checks where evidence shows additional validation is
needed.

Possible future validators include:

- deterministic factual/structural checks where applicable;
- domain-specific validators;
- independent model-based validators;
- consistency checks across generated claims;
- policy-specific validators; and
- provenance/grounding checks for retrieval-backed responses.

Any additional validator must itself have defined failure semantics, cost accounting, and audit
behavior. A validator must not become an unbounded second LLM pipeline.

---

## FS-015 — Longitudinal Human-Agency Evaluation

**Priority:** High  
**Status:** Future  
**Related:** OI-059, Stage 4, Stage 7

Evaluate whether repeated exposure to the runtime changes user behavior over time.

Possible measures:

- scrutiny of AI outputs;
- willingness to override the system;
- ability to identify uncertainty;
- acceptance of deterministic alternatives;
- reliance on AI when it is unnecessary; and
- response to feedforward/confirmation interventions.

### Expected benefit

Tests the project's human-agency claim directly rather than treating transparency as sufficient
evidence of agency preservation.

---

## FS-016 — Output-Side Policy Semantics

**Priority:** Medium  
**Status:** Future  
**Related:** Stage 6, `guardrails/output_filter.py`, current Sprint 5 decision

### Motivation

The current Sprint 5 decision uses the output filter as a leakage/safety check rather than
introducing a broader output-side constitutional policy engine. The existing policy gate remains
the authoritative request-side constitutional control.

### Future extension

Study whether selected policy semantics should also be applied explicitly to generated output,
including how output-side flags interact with validation, repair, withholding, and audit records.

Any such extension must preserve the distinction between request-side policy enforcement and
response validation, and must not silently change current failure semantics.

### Expected benefit

Provides a principled answer to whether some constitutional constraints should be evaluated
symmetrically on inputs and outputs, rather than expanding output policy by implementation
preference alone.

# Activation Criteria

The future-scope registry should not become the next implementation backlog immediately after the
file is created.

Before selecting a future item, the current execution plan should first establish the baseline
system and evaluate the core hypothesis.

At minimum, the project should have:

1. completed the current planned implementation;
2. completed the planned verification/red-team work;
3. established the experimental baseline;
4. measured resource efficiency including runtime overhead;
5. measured decision quality and constitutional compliance;
6. evaluated human-agency effects where currently planned; and
7. documented which limitations materially affected the results.

Only then should future items be prioritized according to evidence from the evaluation.

---

# Prioritization After the Current Plan

The initial recommended order is:

### Phase A — Extend measurement beyond the capstone evaluation
1. FS-003 — Empirical Calibration
2. FS-004 — Independent Classifier Data and Fairness
3. FS-009 — Empirical Energy and Cost Measurement
4. FS-010 — Runtime Breakeven and Overhead Optimization

### Phase B — Strengthen human oversight
5. FS-001 — Human Review and Recourse
6. FS-002 — Structured User Feedback
7. FS-015 — Longitudinal Human-Agency Evaluation

### Phase C — Make repair and routing more capable
8. FS-005 — Resource-Aware Repair Selection
9. FS-006 — Validation and Repair Outcome Learning
10. FS-014 — Stronger Validator Diversity
11. FS-007 — Compound-Request Decomposition
12. FS-016 — Output-Side Policy Semantics

### Phase D — Broaden deployment capability
13. FS-008 — Real Multi-Provider / Model Integration
14. FS-012 — Production-Grade Session Infrastructure
15. FS-013 — Governance Automation
16. FS-011 — Expanded Modality Routing
17. FS-017 - Multilingual routing and safety coverage

This ordering is provisional. Evaluation results from the completed current plan should be allowed
to reorder it.

---

# Relationship to Current Project Records

- `ARCHITECTURE.md` — frozen authority for current architecture.
- `EXECUTION_PLAN.md` — authority for active implementation scope.
- `OPEN_ENDS.md` — authority for unresolved current-scope decisions, defects, and verification
  gaps.
- `RESEARCH_TRACEABILITY.md` — authority for mapping research findings to current design and
  evaluation.
- `FUTURE_SCOPE.md` — registry of intentionally deferred extensions and research directions.

An item should move from this document into `OPEN_ENDS.md` only when it becomes an active
current-scope decision, defect, or verification requirement.

---

## Governance Reminder

Future scope is not permission to bypass the project's constitutional process.

If a future implementation changes:

- a frozen architecture stage;
- a shared schema/interface;
- a security boundary;
- the runtime constitution;
- failure semantics that are architectural rather than implementation-local; or
- another protected project invariant,

the appropriate Change Proposal and owner approval are required before implementation.

The purpose of this document is therefore to preserve **what could make the system better later**
without allowing that possibility to silently expand today's architecture.
