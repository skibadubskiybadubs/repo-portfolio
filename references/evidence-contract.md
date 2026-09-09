# Evidence Contract

## Contents

1. Claim schema
2. Status and source vocabularies
3. Reconciliation
4. Project model
5. Public safety

## Claim schema

The machine-readable vocabulary is also available in [contracts.json](contracts.json).

Use this shape for every meaningful claim:

```json
{
  "id": "ARCH-001",
  "category": "architecture",
  "claim": "The application registers commands through a central registry.",
  "status": "CONFIRMED",
  "sources": [
    {"type": "SOURCE_CODE", "reference": "src/registry.py:Registry"}
  ],
  "career_signals": ["software_architecture", "extensibility"],
  "notes": null,
  "public_safe": false,
  "sensitive": false,
  "supports": [],
  "contradicts": []
}
```

Use uppercase, category-prefixed IDs. Use project-relative references. `sources` may contain `commit`, `timestamp`, `symbol`, or `interview_question_id` in addition to `reference`.

## Status and source vocabularies

Statuses are exactly:

- `CONFIRMED`: directly established by inspectable artifacts.
- `USER_CONFIRMED`: explicitly stated by the user and not independently proven.
- `USER_ESTIMATE`: an approximation supplied by the user.
- `STRONG_INFERENCE`: multiple observations strongly support the interpretation.
- `WEAK_INFERENCE`: plausible but insufficiently supported.
- `USER_CONFIRMATION_REQUIRED`: important hypothesis awaiting the user.
- `UNKNOWN`: no useful evidence.
- `CONTRADICTED`: material sources conflict.

Source types are exactly `SOURCE_CODE`, `TEST`, `CONFIG`, `BUILD_OR_PACKAGE_METADATA`, `GIT_HISTORY`, `DOCUMENTATION`, `SCREENSHOT`, `VIDEO`, `USER_ATTESTATION`, `USER_ESTIMATE`, and `INFERENCE`.

Artifact claims cannot use user sources. Interview claims must use `USER_ATTESTATION` or `USER_ESTIMATE`. Runtime results require evidence from an explicitly authorized verification workflow; static file presence is never enough.

## Reconciliation

- Retain observed and interview stores unchanged as provenance layers.
- Merge claims sharing an ID or connected through `supports` when their meanings agree.
- Preserve all sources and the strongest defensible status; artifact confirmation remains `CONFIRMED`.
- Mark a target claim `CONTRADICTED` when an interview claim lists it in `contradicts`; preserve both claims and explain the conflict in notes.
- Never turn a user estimate into a confirmed fact.
- Never treat Git authorship, repository possession, or a project-wide feature as proof of personal ownership.

## Project model

`project.json` always contains these core keys: `project`, `problem`, `users`, `workflows`, `technology`, `architecture`, `automation`, `testing`, `delivery`, `maintenance`, `ownership`, `impact`, `decisions`, `career_signals`, `unknowns`, and `extensions`.

Extensions are optional maps selected from evidence. Keep web, CAD/BIM, desktop, data/research, plugin, library, CLI, service, or unknown-ecosystem details out of the core when they are not generally comparable.

## Public safety

Default `public_safe` to false for semantic or user-supplied claims. Mark it true only after checking for secrets, private customer/project identities, confidential data, proprietary excerpts, sensitive internal paths, and weak or contested assertions. The generator additionally requires `sensitive: false` and status `CONFIRMED` or `USER_CONFIRMED`.
