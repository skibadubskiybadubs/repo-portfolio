# Evidence Contract

The machine-readable vocabulary is in [contracts.json](contracts.json).

## Claims

Every claim retains `id`, `category`, `claim`, approved `status`, `sources`, `career_signals`, notes, public/sensitive flags, and support/contradiction relationships. It may additionally contain:

- `dimensions`: explicit contextual dimensions supported by the claim;
- `normalized`: structured values stated by evidence;
- `snapshot_id`: repository/media snapshot supporting technical evidence;
- `currency`: `ACTIVE`, `STALE`, or `REVIEW_REQUIRED`;
- `derived_from_claim_ids`: source-layer claims represented by a reconciled claim.

Use project-relative artifact references. Remote media evidence must use the original URL as `reference`; behavioral video evidence also needs `timestamp_seconds` and may include title.

Statuses remain `CONFIRMED`, `USER_CONFIRMED`, `USER_ESTIMATE`, `STRONG_INFERENCE`, `WEAK_INFERENCE`, `USER_CONFIRMATION_REQUIRED`, `UNKNOWN`, and `CONTRADICTED`.

Source types remain `SOURCE_CODE`, `TEST`, `CONFIG`, `BUILD_OR_PACKAGE_METADATA`, `GIT_HISTORY`, `DOCUMENTATION`, `SCREENSHOT`, `VIDEO`, `USER_ATTESTATION`, `USER_ESTIMATE`, and `INFERENCE`.

## Reconciliation

Codex authors canonical reconciliation. Retain all material sources and link every canonical claim to represented observed/interview claim IDs. Never promote an estimate, discard a contradiction, infer personal ownership from Git, or claim runtime success from static evidence. The helper validates these invariants but does not choose semantic winners.

## Project model

Preserve the universal core: `project`, `problem`, `users`, `workflows`, `technology`, `architecture`, `automation`, `testing`, `delivery`, `maintenance`, `ownership`, `impact`, `decisions`, `career_signals`, `unknowns`, and `extensions`.

Add `semantic_summary` entries shaped as `{statement, status, dimensions, evidence_claim_ids}`. Use only active canonical evidence. Optional normalized fields must be directly supplied by linked evidence. Keep ecosystem-specific richness in `extensions`.

## Public safety

Public output may use only explicitly public-safe, non-sensitive `CONFIRMED` or `USER_CONFIRMED` claims. Exclude estimates, inference, contradictions, secrets, private identities, confidential data, proprietary excerpts, and sensitive paths.
