# Installation and Usage

## Install in Codex

Copy or symlink the complete `repo-portfolio` directory into `${CODEX_HOME}/skills/repo-portfolio`. When `CODEX_HOME` is unset, use `~/.codex/skills/repo-portfolio`. Start a new Codex session after installation so the skill is discovered.

The helper requires Python 3.9 or newer and otherwise uses the standard library. `ffmpeg` and `ffprobe` are optional for video preprocessing. `yt-dlp` is optional for explicitly supplied YouTube URLs. The skill never installs these tools automatically.

## Invoke

Run `$repo-portfolio` inside a project or provide a project path. Optional intents:

- `--static`: omit the developer interview while retaining valuable open questions.
- `--deep`: expand scan and semantic investigation depth.
- Resume intent: rerun the same invocation; exact snapshots continue persisted state after compatibility checks.
- `--media <value>`: add a local image/video, local directory, direct HTTP/HTTPS media URL, or YouTube URL. Repeat as needed.

Remote files are cached only under `.repo-portfolio/media/cache/`. Direct images are limited to 25 MiB and direct/YouTube videos to 500 MiB. MIME type and file signatures are checked, private-network destinations and HTML pages are rejected, redirects are bounded, and links inside pages are never followed. The original URL—not the cached filename—remains canonical provenance. YouTube retrieval requires no login and reports private, deleted, restricted, blocked, DRM-protected, or otherwise unavailable videos as warnings rather than aborting the project analysis.

## Outputs

The `.repo-portfolio/` directory contains the dossier, universal project model, observed/interview/canonical evidence stores, prioritized open questions, public-safe summary, media index/frames, analysis plan and coverage, gap analysis, session state, and validation result.

## Safety

Default operation is static. The skill does not execute project code, downloads, installers, builds, tests, package managers, containers, hooks, or migrations. Statements such as “tests pass,” “installer works,” or “application launches” require a separately authorized runtime-verification workflow.
