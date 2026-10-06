# Development Constitution

This document governs **how the project gets built**, not what the
runtime itself does at execution time (that's `config/constitution.yaml`
and `ARCHITECTURE.md`). Think of this as the meta-layer: the rules
that keep Claude, ChatGPT, and the human decision-maker working from
the same source of truth instead of quietly re-architecting the
project independently every session.

This exists because the project's own thesis — that AI should be
constrained by explicit policy rather than left to decide things
freely — should be reflected in how the project itself is built, not
just in what it produces.

---

## Roles

- **Claude** — implementation, code-level analysis, and hands-on
  architecture stress-testing (finding concrete gaps by trying to
  build against the design).
- **ChatGPT** — independent architectural and research review — a
  second reviewer, not a second architect starting from scratch.
- **Human (project owner)** — final authority. Approves or rejects
  every architectural change. Neither AI can unilaterally change
  `ARCHITECTURE.md`.

Both Claude and ChatGPT are implementers/reviewers operating against
`ARCHITECTURE.md` as a shared contract — not competing designers of
their own separate versions.

---

## The five rules

**Rule 1 — Don't use AI unnecessarily.**
If a question can be resolved by deterministic engineering, documentation,
direct code inspection, or testing, don't invoke an LLM to answer it —
including within the development process itself, not just the runtime.

**Rule 2 — Don't redesign without evidence.**
Any change to `ARCHITECTURE.md` requires a documented Change Proposal
(template below). "I think this would be better" is not sufficient
justification on its own — it needs a concrete contradiction, security
flaw, research gap, or implementation impossibility behind it.

**Rule 3 — Research before feature creep.**
Every component in the architecture must trace back to at least one
of: the original problem statement, a specific research finding, an
identified gap, a stated requirement, or a measurable evaluation
criterion. See `RESEARCH_TRACEABILITY.md`. A component that can't be
traced to one of these is a candidate for removal, not a "nice to have."

**Rule 4 — The human remains the final architectural authority.**
Both Claude and ChatGPT can propose, analyze, and disagree. Only the
project owner decides whether a proposed change is accepted, rejected,
or deferred.

**Rule 5 — Optimize for the research contribution, not feature count.**
A 15-module system is not automatically better than a 7-module one. If
a module doesn't sharpen the central hypothesis or the evaluation
framework, it's scope creep, however interesting it seems in isolation.

---

## Change Proposal template

Any proposed change to `ARCHITECTURE.md` — from either Claude or
ChatGPT — must be written up in this format before implementation
begins:

```
CHANGE PROPOSAL

Component:
Current behavior:
Proposed behavior:

Why is the change necessary?
  1. Research justification:
  2. Security justification:
  3. Engineering justification:
  4. Resource-efficiency justification:

Which specific paper/finding does this trace to? (see RESEARCH_TRACEABILITY.md)

What existing component does this affect?

Does it change:
  [ ] architecture (a stage's purpose/inputs/outputs)
  [ ] interfaces (a shared data shape in policy/schemas.py)
  [ ] the runtime constitution (config/constitution.yaml semantics)
  [ ] execution flow (stage ordering, escalation paths)
  [ ] evaluation methodology

What breaks if we don't make this change?

Decision: ACCEPT / REJECT / DEFER
Decided by:
Date:
```

Filling in a `TBD` field in `ARCHITECTURE.md` with real data (e.g.
replacing a placeholder cost number with a measured one) does **not**
require a Change Proposal — that's expected implementation progress.
Changing the *structure* of a stage (its inputs, outputs, ordering
relative to other stages, or security boundary) does.

---

## The working loop

```
                 YOU (project owner)
                  │
          project specification
                  │
          ┌───────┴────────┐
          ▼                ▼
       CLAUDE            CHATGPT
    implementation     architecture /
       analysis        research review
          │                │
          └───────┬────────┘
                  ▼
          CHANGE PROPOSALS
                  │
                  ▼
             YOU DECIDE
                  │
                  ▼
        ARCHITECTURE.md v1.x
                  │
                  ▼
             IMPLEMENT
                  │
                  ▼
               TEST
                  │
                  ▼
             EXPERIMENT
                  │
                  ▼
             EVIDENCE
                  │
                  └────────► next iteration
```

Neither AI proposes a redesign in a vacuum. Both work from
`ARCHITECTURE.md`, flag concrete problems when they find them, and
submit a Change Proposal rather than just implementing (Claude) or
recommending (ChatGPT) a different design outright.
