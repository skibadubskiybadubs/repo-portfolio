# repo-portfolio

## HOW TO USE IT

1. Copy this skill into `${CODEX_HOME}/skills/repo-portfolio` (or `~/.codex/skills/repo-portfolio` when `CODEX_HOME` is unset).
2. Open Codex in the software project you want to analyze.
3. Run `$repo-portfolio`.
4. Optionally provide local or remote screenshots and videos.
5. Answer the adaptive project questions when prompted.
6. Find the evidence dossier and structured outputs under `.repo-portfolio/`.

The normal invocation performs full analysis. Use static mode to skip the interview, deep mode for broader investigation, media input for extra images or videos, and run the skill again to resume compatible saved state.

The directory you supply remains the analysis boundary. Use `--supporting-evidence <file>` for an explicit parent or sibling document without widening it. Repository outputs and working files stay under that directory's `.repo-portfolio/` folder.

Video preprocessing optionally uses `ffmpeg` and `ffprobe`. YouTube retrieval optionally uses `yt-dlp`.

## Example usage

```bash
$repo-portfolio

Run a full analysis of this project.

Additional evidence:

Demo video:
https://www.youtube.com/watch?v=ABC123XYZ

Additional screenshots:
~/PortfolioEvidence/MyTool/screenshots/

Additional local demo:
~/PortfolioEvidence/MyTool/demo-old.mp4

Use all available repository, Git, documentation and media evidence.

First investigate everything that can be established from artifacts.
Then interview me one question at a time only about high-value context that
cannot be reliably determined from those sources.

The goal is the most complete defensible project evidence dossier possible,
not a CV or portfolio yet.
```

## What it is

`repo-portfolio` analyzes a software project, repository, Git history, documentation, and supplied media, then asks targeted questions for context that artifacts cannot prove. It produces evidence-backed structured data for later portfolio case studies, CV/resume generation, VitaeContext or other career knowledge bases, role/seniority analysis, and pricing or consulting analysis. It does not generate the final CV or portfolio itself.
