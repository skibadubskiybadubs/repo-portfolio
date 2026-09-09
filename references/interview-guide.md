# Adaptive Interview Guide

## Build gaps from this project

Do not instantiate a stock questionnaire. Examine active observed claims, coverage findings, profile signals, contradictions, and contextual subdimensions. Select only gaps with meaningful downstream evidence value.

For every gap, decide whether more repository/media inspection can answer it. Route discoverable facts to `ARTIFACT`; route motivation, actual users, ownership, impact, adoption, rationale, constraints, and operational history to `INTERVIEW` when artifacts cannot establish them.

Useful fallback topics include ownership boundaries, original problem, previous workflow, actual users and frequency, outcomes and measurement basis, technical rationale/constraints, and operational lifespan. Use these only when relevant to observed project evidence.

## Score and ask

Supply importance and current completeness to the helper. It calculates the persisted gap score, including contradiction and valuable-inference boosts. Write each interview question yourself and connect it to one scored interview gap plus actual claim, profile, or coverage references.

Ask exactly one question returned by `next-question`. State why the evidence leaves it unresolved. Include a tentative interpretation only when specific observations support it, and invite correction.

## Branch and normalize

Interpret each answer before choosing the next gap:

- A manual workflow may open performer, frequency, pain/error, and before/after dimensions.
- Actual users may open role, internal/external, adoption, support, and lifespan dimensions.
- Team context may open architecture, implementation, UI, deployment, and maintenance ownership.
- A workaround may open constraint, alternative, and tradeoff dimensions.
- A contradiction requires clarification or explicit preservation.

Record the exact answer. Normalize only stated facts. Separate distinct claims. Mark approximations as `USER_ESTIMATE`. If the user does not remember, resolve the question without manufacturing a claim.

Stop when Codex determines no remaining interview gap has sufficient value, the user stops, or only optional unknowns remain. Preserve unresolved gaps in `open_questions.md`.
