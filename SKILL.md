---
name: repo-portfolio
description: >-
  Mine unfamiliar or historical software projects into provenance-backed,
  resumable evidence dossiers. Use when Codex must discover a project, plan
  and perform safe static investigation, inspect Git or local/remote media,
  interview a developer about evidence gaps, reconcile claims, or produce
  machine-readable and human-readable project evidence. Do not use it to
  generate a CV, portfolio, seniority assessment, salary, or pricing advice.
---

# Repo-Portfolio

Recover the maximum defensible technical and contextual evidence from a project. Keep artifact observations, testimony, estimates, inference, contradictions, and unknowns distinct.

Read [references/workflow.md](references/workflow.md) completely before a run. Read [references/evidence-contract.md](references/evidence-contract.md) before writing claims or outputs. Read [references/interview-guide.md](references/interview-guide.md) before generating gaps or questions. See [references/usage.md](references/usage.md) for installation, modes, media, outputs, and requirements.

## Maintain the responsibility boundary

Use the Python helper only for deterministic discovery, schemas, IDs, provenance checks, persistence, coverage state, gap-score calculation, repository compatibility, media retrieval/preprocessing, and validation.

Codex must perform semantic investigation, dynamic planning, architectural/domain interpretation, gap selection and routing, question writing, answer interpretation, reconciliation, normalized project modeling, and dossier synthesis. Do not substitute helper heuristics or a fixed questionnaire for those responsibilities.

Never execute project-owned or downloaded code, builds, tests, installers, package managers, hooks, containers, migrations, or binaries. Read files and use read-only Git commands only. Explicit runtime verification is a separate workflow.

## Run the workflow

1. Resolve the project root and any repeated `--media` inputs. Run discovery:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py analyze <project-root> [--media <path-or-url>] [--deep] [--static]
   ```

2. Interpret `inventory.json`, `project_profile.json`, Git facts, and the media index. Create a project-specific plan payload, then persist it:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py set-plan <project-root> --input <plan.json>
   ```

3. Investigate each planned domain. Ingest observed claims with project-relative symbols/lines, commits, media URLs, and timestamps where available:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py ingest <project-root> --kind observed --input <claims.json>
   ```

4. Record every domain as `COMPLETE`, `PARTIAL`, `NOT_APPLICABLE`, or `BLOCKED`. Give reasons for `PARTIAL` and `BLOCKED` and a reason/evidence basis for `NOT_APPLICABLE`:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py update-coverage <project-root> --input <coverage.json>
   ```

5. After all domains are terminal, decide the meaningful gaps and whether each belongs to further artifact inspection or the interview. Persist Codex-authored gaps and questions:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py set-gaps <project-root> --input <gaps.json>
   python3 <skill-dir>/scripts/repo_portfolio.py queue-question <project-root> --input <question.json>
   python3 <skill-dir>/scripts/repo_portfolio.py next-question <project-root>
   ```

6. Ask exactly the returned question. Interpret the answer into short user claims and dimensions, then ingest it. Recompute meaningful gaps after every answer. Accept “unknown” without invention.
7. Reconcile observed and interview evidence semantically. Preserve every material source, estimate, and unresolved contradiction, then persist Codex's canonical payload:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py set-reconciled <project-root> --input <evidence.json>
   ```

8. Synthesize `project.json`, `dossier.md`, and `public_safe_summary.md`. Include evidence IDs in semantic summaries and dossier claims. Persist them:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py write-outputs <project-root> --input <outputs.json>
   python3 <skill-dir>/scripts/repo_portfolio.py set-interview-state <project-root> --state COMPLETE
   ```

9. Finalize state and validate. Resolve errors before reporting completion:

   ```bash
   python3 <skill-dir>/scripts/repo_portfolio.py finalize <project-root>
   python3 <skill-dir>/scripts/repo_portfolio.py validate <project-root>
   ```

In static mode, do not ask questions. Preserve valuable unresolved gaps in `open_questions.md`; finish after coverage, reconciliation of observed evidence, output synthesis, and validation.

## Handle changed repositories

Respect the compatibility result in `session.json`. Exact snapshots may resume directly. For changed repositories, revalidate stale technical evidence and affected coverage; review preserved user context rather than assuming it still applies. For incompatible identities, technical evidence stays only in the archive; preserved user context is `REVIEW_REQUIRED` and must be reviewed before reuse.

## Finish honestly

`artifact_analysis_finished` means every planned domain reached a valid terminal state, including justified `PARTIAL` or `BLOCKED`. It does not mean evidence is complete. Report `evidence_completeness` and coverage limitations separately. Report completion only when `workflow_complete` and deterministic validation are both true.
