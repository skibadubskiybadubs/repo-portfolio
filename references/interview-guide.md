# Adaptive Interview Guide

## Contents

1. Priority
2. Question construction
3. Branching
4. Answer normalization
5. Stop conditions

## Priority

Prefer gaps in this order, adjusted by the discovered project:

1. Personal ownership and team boundaries.
2. Original problem and previous workflow.
3. Actual users, stakeholders, and frequency.
4. Impact, adoption, and outcomes.
5. Undocumented decisions and external constraints.
6. Maintenance, support, replacement, or abandonment.

Do not ask a contextual question merely because its section is empty. Ask only if the answer could materially improve future evidence use.

## Question construction

Ask one question. State the observations that motivated it. If evidence supports a hypothesis, offer it as tentative—not as fact—and make correction easy. Do not bundle users, impact, ownership, and rationale into one prompt.

## Branching

- A previous manual workflow opens branches for performer, frequency, painful steps, errors, and defensible before/after estimates.
- A newly enabled capability opens branches for why it was previously impossible and who benefited.
- Real users open branches for roles, adoption, frequency, support, and lifespan.
- A team project opens subsystem-specific ownership branches.
- A workaround opens branches for constraints, alternatives, and deliberate tradeoffs.
- A contradiction opens an immediate clarification branch before unrelated questions.

## Answer normalization

Record the exact answer in the question record. Create short normalized claims containing only stated facts. Separate distinct claims. Mark approximate quantities as estimates. Use `supports` and `contradicts` to connect user testimony to observed claims. If the user does not remember, resolve the question without inventing a claim and retain the gap as unknown.

## Stop conditions

Stop when no unresolved contradiction or high-value gap remains, the user asks to stop, or further questioning would produce only optional detail. Preserve medium and low-value questions in `open_questions.md`.
