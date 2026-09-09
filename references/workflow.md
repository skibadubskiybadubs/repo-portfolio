# Workflow Reference

## Contents

1. Modes and phases
2. Discovery and planning
3. Static analysis
4. Completion behavior

## Modes and phases

- **Default**: discover, analyze, interview, reconcile, generate, validate.
- **Static**: perform every phase except the interview; preserve questions for later.
- **Deep**: increase scan budgets and inspect additional architectural and historical seams.
- **Media**: include one or more repository-external image/video paths.
- **Resume**: continue the persisted session and pending interview without discarding earlier answers.

The persisted phases are `discovered`, `artifact_analysis`, `interview_ready`, `interviewing`, `complete`, and `static_complete`.

## Discovery and planning

Start from structure, extensions, manifests, build/configuration files, CI, tests, documentation, entry points, Git metadata, installers, deployment assets, and media. Infer a provisional profile. If an ecosystem is unknown, derive an investigation brief from its manifests, file clusters, naming conventions, entry points, and dependency declarations.

Always consider product/purpose and architecture. Select other domains only when evidence makes them relevant: automation/domain rules, interface/UX, testing, delivery, reliability, performance, maintenance, decisions, integrations, and ecosystem-specific extensions.

## Static analysis

Prioritize evidence that changes the project model:

1. Entry points, public interfaces, workflows, and component boundaries.
2. Domain transformations, validation, orchestration, and human interaction points.
3. Test types and what behavior they assert, without claiming they pass.
4. Packaging, installation, CI/deployment definitions, diagnostics, and configuration.
5. Git evolution: lifespan, releases, migrations, refactors, maintenance, test growth, and contributor context.
6. Media-visible workflows and results with filenames and timestamps.

Do not inspect generated/vendor directories unless they are themselves relevant evidence. Do not copy credentials, customer data, tokens, private URLs, or large proprietary excerpts into outputs.

## Completion behavior

Reconcile after every meaningful evidence batch. A valid run produces the universal machine-readable model, three evidence stores, dossier, prioritized questions, sanitized summary, media index, and resumable state. Unknowns are a valid outcome. Validation success means the dossier is internally consistent, not that project runtime behavior was verified.
