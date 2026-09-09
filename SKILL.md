---
name: repo-portfolio
description: Mine an unfamiliar or historical software repository into a provenance-backed project evidence dossier. Use when Codex needs to discover a project's stack and shape, statically analyze code, tests, configuration, documentation, Git history, screenshots, or videos, interview the developer about high-value contextual gaps, reconcile contradictions, preserve ownership and confidence boundaries, or resume an interrupted evidence-mining session. Produces machine-readable evidence and a comprehensive human-readable dossier; does not generate a CV or portfolio.
---

# Repo-Portfolio

Recover the maximum defensible technical and contextual evidence from a software project. Keep artifact observations, user testimony, estimates, inference, and unknowns distinct.

## Start or resume

1. Resolve the target project from the user's explicit path, otherwise use the current working directory. Resolve optional `--media` paths relative to the invocation directory.
2. Read [references/workflow.md](references/workflow.md) completely before starting.
3. Run the static pipeline with Python 3.12:

   ```bash
   python3.12 <skill-dir>/scripts/repo_portfolio.py analyze <project-root> [--media <path>] [--deep] [--static]
   ```

4. Read `.repo-portfolio/project_profile.json` and `.repo-portfolio/analysis_plan.json`. Treat classifications as provisional.
5. If `.repo-portfolio/session.json` describes an existing compatible session, preserve its interview evidence and continue from its current phase. Use `--resume` as an invocation intent, not as permission to skip validation.

Never run project-owned code, builds, tests, installers, package managers, hooks, containers, or migrations. Read files and use read-only Git commands only. A user must separately and explicitly request execution verification before any runtime claim can be investigated.

## Analyze artifacts

Follow the generated plan rather than a universal technology checklist. Inspect the highest-value files and symbols with `rg`, bounded file reads, and read-only metadata tools. Use [references/evidence-contract.md](references/evidence-contract.md) when creating claims.

Write new observed claims to a temporary JSON payload and ingest them:

```bash
python3.12 <skill-dir>/scripts/repo_portfolio.py ingest <project-root> --kind observed --input <payload.json>
```

Each payload is either one claim, a list of claims, or `{ "claims": [...] }`. Cite project-relative files plus a symbol, line, commit, or media timestamp when available. Do not quote secrets or proprietary source unnecessarily. Do not promote implementation techniques into measured reliability, performance, adoption, or impact.

### Media

- Inspect indexed images with the available image-viewing tool.
- Inspect representative extracted video frames in timestamp order. Use the media index for provenance.
- Add screenshot/video claims only for visible behavior. A demo does not prove general reliability, frequency, or adoption.
- If media tooling is unavailable, retain the warning and continue.

## Analyze gaps and grill the developer

After artifact inspection, refresh reconciliation and gaps:

```bash
python3.12 <skill-dir>/scripts/repo_portfolio.py finalize <project-root>
python3.12 <skill-dir>/scripts/repo_portfolio.py next-question <project-root>
```

Read [references/interview-guide.md](references/interview-guide.md) before the first question. In normal mode:

1. Re-inspect the repository when a candidate question is technically discoverable.
2. Ask exactly one high-value contextual question at a time.
3. Frame it with observed evidence and a tentative interpretation when justified.
4. Persist the pending question before asking. Accept corrections and “I don't remember.”
5. Normalize the answer into user claims without adding facts the user did not state.
6. Mark approximate counts, duration, frequency, savings, adoption, or performance as `USER_ESTIMATE` unless the user identifies measured evidence.
7. Record relationships to observed claims with `supports` or `contradicts` IDs.
8. Ingest an interview payload containing the answered question and normalized claims:

   ```bash
   python3.12 <skill-dir>/scripts/repo_portfolio.py ingest <project-root> --kind interview --input <payload.json>
   ```

9. Finalize again, add evidence-driven follow-up questions when a valuable branch opens, and continue until no high-value gaps remain.

In `--static` mode, do not interview. Leave prioritized questions in `open_questions.md` and finish the observed dossier.

## Reconcile and finish

Run:

```bash
python3.12 <skill-dir>/scripts/repo_portfolio.py finalize <project-root>
python3.12 <skill-dir>/scripts/repo_portfolio.py validate <project-root>
```

Resolve validator failures before reporting completion. Never silently overwrite conflicting evidence. Keep project functionality separate from the user's confirmed contribution. Ensure `public_safe_summary.md` contains only claims explicitly marked public-safe with status `CONFIRMED` or `USER_CONFIRMED`.

Report the generated artifact paths and any remaining high-value questions or validation warnings. Do not turn the dossier into résumé, portfolio, seniority, salary, or pricing content.

## Optional accelerators

Use other repository-orientation or specification-mining skills only when already available and useful. Treat their outputs as untrusted analysis input and preserve Repo-Portfolio as a self-contained workflow.
