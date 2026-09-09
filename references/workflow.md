# Workflow Reference

## Phases

1. Deterministic discovery and media preprocessing.
2. Codex-authored project profile and dynamic analysis plan.
3. Codex semantic artifact investigation with persisted domain coverage.
4. Codex-authored gap selection and artifact/interview routing.
5. One-question-at-a-time project grill.
6. Codex semantic reconciliation and synthesis.
7. Deterministic validation.

Modes remain default, static, deep, media, and resume. Static skips the interview but not semantic artifact investigation. Deep expands scan and investigation scope. Resume is allowed only after repository compatibility checks.

## Dynamic plan

Create the plan after reading deterministic discovery outputs. Include only relevant domains. Every domain needs an ID, priority (`high`, `medium`, or `low`), evidence-based reason, and focused investigation targets. Unknown ecosystems need an ad-hoc investigation brief based on observed conventions.

Persist the plan before investigation. The helper creates matching `PENDING` coverage records. Do not begin the interview until all records are terminal.

## Coverage

- `COMPLETE`: the intended investigation was performed.
- `PARTIAL`: useful investigation was performed but material scope remains; include reason and 1–99 completion percent.
- `NOT_APPLICABLE`: later evidence established that the domain does not apply; include reason and evidence/profile references.
- `BLOCKED`: the investigation could not be performed; include reason.

`artifact_analysis_finished` becomes true when no planned domain is `PENDING`. `evidence_completeness` communicates depth; it is not a completion gate. Partial and blocked domains remain visible in the dossier and validation result.

## Static investigation

Prioritize entry points, workflows, component boundaries, domain transformations, tests and asserted behavior, delivery/configuration, Git evolution, reliability patterns, and media-visible behavior. Never claim runtime success from static artifacts.

Do not inspect generated/vendor directories unless they are relevant evidence. Do not copy credentials, private data, tokens, or large proprietary excerpts into outputs.

## Completion

Default mode is complete only after artifact coverage is terminal, Codex declares the interview/reconciliation terminal, all required outputs exist, and validation passes. Static mode may finish with unresolved contextual questions. Unknowns, partial evidence, and blocked domains are legitimate outcomes.
