#!/usr/bin/env python3
"""Deterministic infrastructure for the Repo-Portfolio Codex skill.

Semantic planning, investigation, interviewing, reconciliation, and synthesis
belong to Codex. This helper owns safe discovery, state, persistence, media
preprocessing, scoring, compatibility, and validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Running the installed skill must not mutate its own directory.
sys.dont_write_bytecode = True
from media_support import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, collect_media


SCHEMA_VERSION = "1.1"
SUPPORTED_LEGACY = {"1.0", SCHEMA_VERSION}
MIN_PYTHON = (3, 9)
OUTPUT_NAME = ".repo-portfolio"
COVERAGE_STATES = {"PENDING", "COMPLETE", "PARTIAL", "NOT_APPLICABLE", "BLOCKED"}
TERMINAL_COVERAGE = COVERAGE_STATES - {"PENDING"}
PRIORITY_WEIGHTS = {"high": 3, "medium": 2, "low": 1}
INTERVIEW_STATES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETE", "STOPPED_WITH_UNKNOWNS", "NOT_APPLICABLE"}
STATUSES = {
    "CONFIRMED", "USER_CONFIRMED", "USER_ESTIMATE", "STRONG_INFERENCE",
    "WEAK_INFERENCE", "USER_CONFIRMATION_REQUIRED", "UNKNOWN", "CONTRADICTED",
}
STATUS_COMPLETENESS = {
    "CONFIRMED": 100, "USER_CONFIRMED": 100, "USER_ESTIMATE": 75,
    "STRONG_INFERENCE": 65, "WEAK_INFERENCE": 30,
    "USER_CONFIRMATION_REQUIRED": 15, "UNKNOWN": 0, "CONTRADICTED": 10,
}
SOURCE_TYPES = {
    "SOURCE_CODE", "TEST", "CONFIG", "BUILD_OR_PACKAGE_METADATA", "GIT_HISTORY",
    "DOCUMENTATION", "SCREENSHOT", "VIDEO", "USER_ATTESTATION", "USER_ESTIMATE", "INFERENCE",
}
ARTIFACT_SOURCES = SOURCE_TYPES - {"USER_ATTESTATION", "USER_ESTIMATE"}
CURRENCIES = {"ACTIVE", "STALE", "REVIEW_REQUIRED"}
CORE_KEYS = [
    "project", "problem", "users", "workflows", "technology", "architecture",
    "automation", "testing", "delivery", "maintenance", "ownership", "impact",
    "decisions", "career_signals", "unknowns", "extensions",
]
REQUIRED_OUTPUTS = [
    "dossier.md", "project.json", "observed_evidence.json", "interview_evidence.json",
    "evidence.json", "open_questions.md", "public_safe_summary.md", "media/media_index.json",
]
REQUIRED_DIRECTORIES = ["media/extracted_frames"]
IGNORED_DIRS = {
    ".git", OUTPUT_NAME, ".hg", ".svn", ".idea", ".vscode", "node_modules", "vendor",
    "dist", "build", "target", "coverage", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".venv", "venv",
}
LANGUAGE_EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".cs": "C#", ".java": "Java", ".kt": "Kotlin",
    ".kts": "Kotlin", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++",
    ".hpp": "C++", ".r": "R", ".scala": "Scala", ".lua": "Lua", ".sh": "Shell",
    ".ps1": "PowerShell", ".sql": "SQL", ".html": "HTML", ".css": "CSS",
    ".vue": "Vue", ".svelte": "Svelte",
}
TEXT_EXTENSIONS = set(LANGUAGE_EXTENSIONS) | {
    ".json", ".toml", ".yaml", ".yml", ".xml", ".ini", ".cfg", ".md", ".txt",
    ".gradle", ".properties",
}
MANIFEST_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile", "poetry.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.toml",
    "cargo.lock", "go.mod", "go.sum", "pom.xml", "build.gradle", "build.gradle.kts",
    "gemfile", "composer.json", "mix.exs", "pubspec.yaml", "cmakelists.txt", "makefile", "dockerfile",
}
SENSITIVE_NAME_RE = re.compile(
    r"(^|[._-])(secret|credential|token|password|private|customer|client-data)([._-]|$)|"
    r"(^|/)(\.env($|\.)|id_rsa|id_ed25519|.*\.pem$|.*\.key$)", re.I,
)
CATEGORY_PREFIX = {
    "project": "PROJ", "product": "PROD", "problem": "PROB", "users": "USER",
    "workflow": "FLOW", "previous_workflow": "PREV", "automation": "AUTO",
    "domain": "DOMAIN", "architecture": "ARCH", "interface": "UX", "integration": "INT",
    "testing": "TEST", "reliability": "REL", "performance": "PERF",
    "installation": "INST", "delivery": "DELIV", "configuration": "CONF",
    "maintenance": "MAINT", "git_history": "GIT", "decisions": "DEC",
    "constraints": "CONST", "ownership": "OWN", "impact": "IMPACT",
    "technology": "TECH", "documentation": "DOC", "media": "MEDIA",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def output_dir(project: Path, explicit: str | None = None) -> Path:
    return Path(explicit).expanduser().resolve() if explicit else project / OUTPUT_NAME


def is_sensitive(reference: str) -> bool:
    return bool(SENSITIVE_NAME_RE.search(reference.replace("\\", "/")))


def classify_kind(relative: str, suffix: str) -> str:
    lowered = relative.lower()
    name = Path(lowered).name
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if "test" in Path(lowered).parts or re.search(r"(^|[._-])(test|spec)([._-]|$)", name):
        return "test"
    if lowered.startswith(".github/workflows/") or any(value in name for value in ("gitlab-ci", "jenkinsfile", "azure-pipelines")):
        return "ci"
    if name in MANIFEST_NAMES or suffix in {".csproj", ".sln", ".fsproj"}:
        return "build_or_package"
    if name.startswith(("readme", "changelog", "contributing")) or lowered.startswith("docs/"):
        return "documentation"
    if any(value in lowered for value in ("install", "setup", "deploy", "docker", "helm", "terraform")):
        return "delivery"
    if suffix in {".json", ".toml", ".yaml", ".yml", ".xml", ".ini", ".cfg", ".properties"}:
        return "config"
    if suffix in LANGUAGE_EXTENSIONS:
        return "source"
    return "other"


def inventory_project(project: Path, deep: bool) -> dict[str, Any]:
    file_limit = 50000 if deep else 12000
    hash_budget = 1024 * 1024 * 1024 if deep else 256 * 1024 * 1024
    hashed = 0
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    truncated = False
    for root, dirs, files in os.walk(project, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if d.lower() not in IGNORED_DIRS and not (root_path / d).is_symlink())
        for filename in sorted(files):
            path = root_path / filename
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            relative = path.relative_to(project).as_posix()
            suffix = path.suffix.lower()
            content_hash = None
            if hashed < hash_budget:
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as handle:
                        while hashed < hash_budget:
                            chunk = handle.read(min(1024 * 1024, hash_budget - hashed))
                            if not chunk:
                                break
                            digest.update(chunk)
                            hashed += len(chunk)
                    content_hash = digest.hexdigest()
                except OSError:
                    pass
            entries.append({
                "path": relative, "extension": suffix, "size": stat.st_size,
                "kind": classify_kind(relative, suffix), "sensitive_name": is_sensitive(relative),
                "content_sha256": content_hash,
            })
            if len(entries) >= file_limit:
                truncated = True
                warnings.append(f"Inventory capped at {file_limit} files; use --deep for a larger budget.")
                break
        if truncated:
            break
    if hashed >= hash_budget:
        warnings.append(f"Content hashing reached its {hash_budget // (1024 * 1024)} MiB budget.")
    kinds = Counter(item["kind"] for item in entries)
    extensions = Counter(item["extension"] for item in entries if item["extension"])
    fingerprint = canonical_digest([(item["path"], item["size"], item["content_sha256"]) for item in entries])
    structure = canonical_digest({
        "manifests": sorted(item["path"] for item in entries if item["kind"] == "build_or_package"),
        "top": sorted({item["path"].split("/", 1)[0] for item in entries}),
        "extensions": sorted(extensions),
    })
    return {
        "schema_version": SCHEMA_VERSION, "generated_at": now(), "project_root": str(project),
        "file_count": len(entries), "truncated": truncated, "fingerprint": fingerprint,
        "structure_signature": structure, "hashed_bytes": hashed,
        "counts_by_kind": dict(sorted(kinds.items())),
        "counts_by_extension": dict(extensions.most_common()), "files": entries, "warnings": warnings,
    }


def discovery_profile(inventory: dict[str, Any]) -> dict[str, Any]:
    languages = Counter()
    manifests = []
    for item in inventory["files"]:
        language = LANGUAGE_EXTENSIONS.get(item["extension"])
        if language and item["kind"] in {"source", "test"}:
            languages[language] += 1
        if item["kind"] == "build_or_package":
            manifests.append(item["path"])
    return {
        "schema_version": SCHEMA_VERSION, "generated_at": now(), "provisional": True,
        "deterministic_signals": {
            "languages": [{"name": key, "file_count": value} for key, value in languages.most_common()],
            "manifests": manifests,
            "counts_by_kind": inventory["counts_by_kind"],
            "top_level": sorted({item["path"].split("/", 1)[0] for item in inventory["files"]})[:100],
            "has_git": False, "has_media": any(item["kind"] in {"image", "video"} for item in inventory["files"]),
        },
        "codex_profile": None,
    }


def run_git(args: list[str], project: Path, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=project, capture_output=True, text=True, timeout=timeout,
            check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"},
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def git_facts(project: Path) -> dict[str, Any]:
    code, _, _ = run_git(["rev-parse", "--is-inside-work-tree"], project)
    if code:
        return {"available": False, "warnings": ["No readable Git work tree was found."]}
    _, root, _ = run_git(["rev-parse", "--show-toplevel"], project)
    _, head, _ = run_git(["rev-parse", "HEAD"], project)
    _, tree, _ = run_git(["rev-parse", "HEAD^{tree}"], project)
    _, roots, _ = run_git(["rev-list", "--max-parents=0", "HEAD"], project)
    _, remote, _ = run_git(["config", "--get", "remote.origin.url"], project)
    _, status, _ = run_git(["status", "--porcelain=v1", "--untracked-files=all"], project)
    def belongs_to_output(line: str) -> bool:
        paths = line[3:].split(" -> ") if len(line) >= 4 else [line]
        return any(path.strip('"') == OUTPUT_NAME or path.strip('"').startswith(f"{OUTPUT_NAME}/") for path in paths)
    status = "\n".join(line for line in status.splitlines() if not belongs_to_output(line))
    _, log, log_error = run_git([
        "log", "--date=iso-strict", "--pretty=format:%H%x09%aI%x09%an%x09%ae%x09%s", "-n", "5000",
    ], project)
    commits = []
    for line in log.splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5:
            commits.append({"hash": parts[0], "date": parts[1], "author": parts[2], "email": parts[3], "subject": parts[4]})
    contributors = Counter((item["author"], item["email"]) for item in commits)
    _, tags, _ = run_git(["tag", "--list"], project)
    return {
        "available": True, "repository_root": root, "head": head or None, "tree": tree or None,
        "root_commits": roots.splitlines(), "remote_hash": hashlib.sha256(remote.encode()).hexdigest() if remote else None,
        "dirty_digest": hashlib.sha256(status.encode()).hexdigest(), "commit_count_scanned": len(commits),
        "first_commit_date": commits[-1]["date"] if commits else None,
        "latest_commit_date": commits[0]["date"] if commits else None,
        "contributors": [{"name": name, "email": email, "commits_scanned": count} for (name, email), count in contributors.most_common()],
        "tags": tags.splitlines()[:500] if tags else [], "recent_commits": commits[:100],
        "warnings": [log_error] if log_error and not commits else [],
    }


def repository_identity(project: Path, inventory: dict[str, Any], git: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    root_hash = hashlib.sha256(str(project.resolve()).encode()).hexdigest()
    if git.get("available"):
        try:
            relative_root = project.resolve().relative_to(Path(git["repository_root"]).resolve()).as_posix()
        except (KeyError, ValueError):
            relative_root = "."
        identity_basis = {"roots": git.get("root_commits"), "remote": git.get("remote_hash"), "project_subpath": relative_root}
        identity_id = canonical_digest(identity_basis)
        kind = "git"
    else:
        prior_identity = (prior or {}).get("repository_identity", {})
        if prior_identity.get("root_path_hash") == root_hash:
            identity_id = prior_identity.get("id") or uuid.uuid4().hex
        else:
            identity_id = uuid.uuid4().hex
        kind = "filesystem"
    snapshot_basis = {
        "identity": identity_id, "inventory": inventory["fingerprint"],
        "head": git.get("head"), "tree": git.get("tree"), "dirty": git.get("dirty_digest"),
    }
    return {
        "id": identity_id, "kind": kind, "root_path_hash": root_hash,
        "structure_signature": inventory["structure_signature"],
        "git_root_commits": git.get("root_commits", []), "git_remote_hash": git.get("remote_hash"),
        "snapshot_id": canonical_digest(snapshot_basis),
    }


def compatibility(prior: dict[str, Any], identity: dict[str, Any], inventory: dict[str, Any]) -> str:
    if not prior:
        return "NEW"
    if prior.get("schema_version") not in SUPPORTED_LEGACY:
        return "INCOMPATIBLE_SCHEMA"
    previous = prior.get("repository_identity")
    if not previous:
        return "CHANGED" if prior.get("project_root") else "INCOMPATIBLE_IDENTITY"
    if previous.get("id") != identity["id"]:
        return "INCOMPATIBLE_IDENTITY"
    if previous.get("snapshot_id") == identity["snapshot_id"]:
        return "EXACT"
    if identity["kind"] == "filesystem" and previous.get("structure_signature") != inventory["structure_signature"]:
        old_entries = (read_json(Path(prior.get("output_directory", "")) / "inventory.json", {}) or {}).get("files", [])
        old_files = {item.get("path") for item in old_entries}
        new_files = {item.get("path") for item in inventory.get("files", [])}
        union = old_files | new_files
        similarity = len(old_files & new_files) / len(union) if union else 1.0
        if old_files and similarity < 0.35:
            return "AMBIGUOUS_IDENTITY"
    return "CHANGED"


def archive_session(out: Path, session: dict[str, Any]) -> str | None:
    if not session:
        return None
    archive_id = session.get("session_id", datetime.now().strftime("%Y%m%d%H%M%S"))
    destination = out / "history" / archive_id
    destination.mkdir(parents=True, exist_ok=True)
    for relative in REQUIRED_OUTPUTS + [
        "session.json", "inventory.json", "project_profile.json", "analysis_plan.json",
        "analysis_coverage.json", "gap_analysis.json", "git_history.json", "validation.json",
    ]:
        source = out / relative
        if source.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    if (out / "media").is_dir():
        shutil.copytree(out / "media", destination / "media", dirs_exist_ok=True)
    return destination.relative_to(out).as_posix()


def empty_store(kind: str) -> dict[str, Any]:
    value = {"schema_version": SCHEMA_VERSION, "updated_at": now(), "claims": []}
    if kind == "interview":
        value["questions"] = []
    return value


def mark_claims(data: dict[str, Any], currency: str) -> dict[str, Any]:
    for item in data.get("claims", []):
        item["currency"] = currency
    if "questions" in data:
        for question in data["questions"]:
            if question.get("status") in {"open", "pending"}:
                question["status"] = "STALE"
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at"] = now()
    return data


def current_snapshot(project: Path, deep: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    inventory = inventory_project(project, deep)
    git = git_facts(project)
    return inventory, git


def ensure_snapshot(project: Path, out: Path) -> tuple[bool, str | None]:
    session = read_json(out / "session.json", {})
    inventory, git = current_snapshot(project, session.get("mode") == "deep")
    identity = repository_identity(project, inventory, git, session)
    if identity["snapshot_id"] != session.get("repository_identity", {}).get("snapshot_id"):
        return False, "Repository state changed after discovery; rerun analyze before continuing."
    return True, None


def normalize_claim(item: dict[str, Any], kind: str, snapshot_id: str) -> dict[str, Any]:
    status = str(item.get("status", "USER_CONFIRMED" if kind == "interview" else "CONFIRMED")).upper()
    sources = list(item.get("sources", []))
    if kind == "interview" and not sources:
        source_type = "USER_ESTIMATE" if status == "USER_ESTIMATE" else "USER_ATTESTATION"
        question_id = item.get("interview_question_id")
        sources = [{"type": source_type, "reference": question_id or "interview", "interview_question_id": question_id}]
    return {
        "id": str(item.get("id", "")).strip(), "category": str(item.get("category", "project")).lower().strip(),
        "claim": str(item.get("claim", "")).strip(), "status": status, "sources": sources,
        "career_signals": sorted(set(map(str, item.get("career_signals", [])))), "notes": item.get("notes"),
        "public_safe": bool(item.get("public_safe", False)), "sensitive": bool(item.get("sensitive", False)),
        "supports": list(item.get("supports", [])), "contradicts": list(item.get("contradicts", [])),
        "dimensions": sorted(set(map(str, item.get("dimensions", [])))), "normalized": dict(item.get("normalized", {})),
        "snapshot_id": item.get("snapshot_id") or snapshot_id, "currency": item.get("currency", "ACTIVE"),
        "derived_from_claim_ids": list(item.get("derived_from_claim_ids", [])), "origin": kind,
    }


def assign_ids(claims: list[dict[str, Any]], existing: Iterable[str]) -> None:
    used = set(existing)
    counters: defaultdict[str, int] = defaultdict(int)
    for value in used:
        match = re.fullmatch(r"([A-Z]+)-(\d+)", value)
        if match:
            counters[match.group(1)] = max(counters[match.group(1)], int(match.group(2)))
    for item in claims:
        if item.get("id") and item["id"] not in used:
            used.add(item["id"])
            continue
        prefix = CATEGORY_PREFIX.get(item.get("category"), "EVID")
        counters[prefix] += 1
        while f"{prefix}-{counters[prefix]:03d}" in used:
            counters[prefix] += 1
        item["id"] = f"{prefix}-{counters[prefix]:03d}"
        used.add(item["id"])


def payload_claims(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("claims"), list):
        return payload["claims"]
    if isinstance(payload, dict) and "claim" in payload:
        return [payload]
    return []


def coverage_metrics(plan: dict[str, Any], coverage: dict[str, Any]) -> tuple[bool, float]:
    records = {item["domain_id"]: item for item in coverage.get("domains", [])}
    finished = bool(plan.get("domains")) and all(records.get(item["id"], {}).get("state") in TERMINAL_COVERAGE for item in plan["domains"])
    numerator = denominator = 0.0
    for domain in plan.get("domains", []):
        record = records.get(domain["id"], {})
        if record.get("state") == "NOT_APPLICABLE":
            continue
        weight = PRIORITY_WEIGHTS.get(domain.get("priority"), 1)
        denominator += weight * 100
        state = record.get("state", "PENDING")
        value = 100 if state == "COMPLETE" else record.get("completion_percent", 0) if state == "PARTIAL" else 0
        numerator += weight * value
    return finished, round(numerator / denominator * 100, 1) if denominator else 100.0


def invalidate_session(session: dict[str, Any]) -> None:
    session["state_revision"] = int(session.get("state_revision", 0)) + 1
    session["validated_revision"] = None
    session["workflow_complete"] = False


def refresh_session(out: Path) -> dict[str, Any]:
    session = read_json(out / "session.json", {})
    plan = read_json(out / "analysis_plan.json", {})
    coverage = read_json(out / "analysis_coverage.json", {})
    finished, completeness = coverage_metrics(plan, coverage)
    session["artifact_analysis_finished"] = finished
    session["evidence_completeness"] = completeness
    required_present = all((out / relative).is_file() for relative in REQUIRED_OUTPUTS) and all(
        (out / relative).is_dir() for relative in REQUIRED_DIRECTORIES
    )
    interview_terminal = session.get("interview_state") in {"COMPLETE", "STOPPED_WITH_UNKNOWNS", "NOT_APPLICABLE"}
    if session.get("mode") == "static":
        interview_terminal = True
    ready = bool(finished and interview_terminal and required_present and session.get("reconciliation_ready") and session.get("outputs_ready"))
    session["workflow_complete"] = bool(ready and session.get("validated_revision") == session.get("state_revision"))
    session["phase"] = (
        "complete" if session["workflow_complete"] else
        "interviewing" if session.get("pending_question_id") else
        "interview_ready" if finished and session.get("mode") != "static" else
        "artifact_analysis"
    )
    session["updated_at"] = now()
    atomic_json(out / "session.json", session)
    return session


def render_open_questions(out: Path) -> None:
    gaps = read_json(out / "gap_analysis.json", {"gaps": []}).get("gaps", [])
    questions = read_json(out / "interview_evidence.json", {"questions": []}).get("questions", [])
    question_by_gap = {item.get("gap_id"): item for item in questions}
    active = [item for item in gaps if item.get("status", "open") == "open"]
    lines = ["# Open Questions", "", "Codex-selected unresolved evidence gaps.", ""]
    for priority, heading in (("high", "High Value"), ("medium", "Medium Value"), ("low", "Low Value / Optional")):
        lines += [f"## {heading}", ""]
        selected = [item for item in active if item["priority"] == priority]
        if not selected:
            lines.append("- None.")
        for gap in sorted(selected, key=lambda item: (-item["gap_score"], item["id"])):
            question = question_by_gap.get(gap["id"])
            text = question.get("question") if question else gap["rationale"]
            lines.append(f"- **{gap['id']}** ({gap['resolution_channel']}, score {gap['gap_score']}): {text}")
        lines.append("")
    atomic_text(out / "open_questions.md", "\n".join(lines))


def analyze(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}", file=sys.stderr)
        return 2
    out = output_dir(project, args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "media" / "extracted_frames").mkdir(parents=True, exist_ok=True)
    prior_session = read_json(out / "session.json", {})
    prior_observed = read_json(out / "observed_evidence.json", empty_store("observed"))
    prior_interview = read_json(out / "interview_evidence.json", empty_store("interview"))
    inventory, git = current_snapshot(project, args.deep)
    identity = repository_identity(project, inventory, git, prior_session)
    result = compatibility(prior_session, identity, inventory)
    archive = None
    if result in {"INCOMPATIBLE_SCHEMA", "INCOMPATIBLE_IDENTITY", "AMBIGUOUS_IDENTITY"}:
        archive = archive_session(out, prior_session)
        observed = empty_store("observed")
        interview = (
            mark_claims(prior_interview, "REVIEW_REQUIRED")
            if result in {"INCOMPATIBLE_IDENTITY", "AMBIGUOUS_IDENTITY"}
            else empty_store("interview")
        )
    elif result == "CHANGED":
        observed = mark_claims(prior_observed, "STALE")
        interview = mark_claims(prior_interview, "REVIEW_REQUIRED")
    elif result == "EXACT":
        observed, interview = prior_observed, prior_interview
    else:
        observed, interview = empty_store("observed"), empty_store("interview")
    if result == "EXACT" and not args.media:
        media = read_json(out / "media" / "media_index.json", None) or collect_media(project, inventory["files"], [], out)
    else:
        media = collect_media(project, inventory["files"], args.media or [], out)
    profile = discovery_profile(inventory)
    profile["deterministic_signals"]["has_git"] = bool(git.get("available"))
    session = {
        "schema_version": SCHEMA_VERSION, "session_id": prior_session.get("session_id") if result == "EXACT" else uuid.uuid4().hex,
        "project_root": str(project), "output_directory": str(out), "repository_identity": identity,
        "compatibility": result, "previous_archive": archive,
        "mode": "static" if args.static else ("deep" if args.deep else "default"),
        "phase": "artifact_analysis",
        "interview_state": (
            "NOT_APPLICABLE" if args.static else
            prior_session.get("interview_state", "NOT_STARTED") if result == "EXACT" else
            "NOT_STARTED"
        ),
        "pending_question_id": None if result != "EXACT" else prior_session.get("pending_question_id"),
        "artifact_analysis_finished": False, "evidence_completeness": 0.0, "workflow_complete": False,
        "reconciliation_ready": bool(prior_session.get("reconciliation_ready")) if result == "EXACT" else False,
        "outputs_ready": bool(prior_session.get("outputs_ready")) if result == "EXACT" else False,
        "state_revision": int(prior_session.get("state_revision", 0)) + 1,
        "validated_revision": None,
        "created_at": prior_session.get("created_at", now()) if result == "EXACT" else now(), "updated_at": now(),
        "warnings": inventory["warnings"] + git.get("warnings", []) + media.get("warnings", []),
    }
    atomic_json(out / "session.json", session)
    atomic_json(out / "inventory.json", inventory)
    atomic_json(out / "project_profile.json", profile)
    atomic_json(out / "git_history.json", git)
    atomic_json(out / "media" / "media_index.json", media)
    atomic_json(out / "observed_evidence.json", observed)
    atomic_json(out / "interview_evidence.json", interview)
    if result != "EXACT":
        atomic_json(out / "analysis_plan.json", {"schema_version": SCHEMA_VERSION, "snapshot_id": identity["snapshot_id"], "plan_id": None, "domains": [], "dimensions": []})
        atomic_json(out / "analysis_coverage.json", {"schema_version": SCHEMA_VERSION, "snapshot_id": identity["snapshot_id"], "plan_id": None, "domains": []})
        atomic_json(out / "gap_analysis.json", {"schema_version": SCHEMA_VERSION, "snapshot_id": identity["snapshot_id"], "dimensions": [], "gaps": []})
        atomic_json(out / "evidence.json", empty_store("canonical"))
    render_open_questions(out)
    print(json.dumps({"output": str(out), "compatibility": result, "snapshot_id": identity["snapshot_id"], "next_action": "Codex must create and persist the dynamic analysis plan."}, indent=2))
    return 0


def load_payload(path: str) -> Any:
    value = read_json(Path(path).expanduser().resolve(), None)
    if value is None:
        raise ValueError("Input payload is not valid JSON.")
    return value


def set_plan(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    try:
        payload = load_payload(args.input)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    domains = payload.get("domains", [])
    errors = []
    ids = set()
    for item in domains:
        domain_id = item.get("id")
        if not domain_id or domain_id in ids:
            errors.append("Plan domains require unique non-empty IDs.")
        ids.add(domain_id)
        if item.get("priority") not in PRIORITY_WEIGHTS:
            errors.append(f"Domain {domain_id} has invalid priority.")
        if not item.get("reason") or not item.get("focus"):
            errors.append(f"Domain {domain_id} requires an evidence-based reason and focus list.")
    if not domains:
        errors.append("The Codex-authored plan must contain at least one domain.")
    if errors:
        print(json.dumps({"errors": errors}, indent=2), file=sys.stderr)
        return 2
    session = read_json(out / "session.json", {})
    plan_body = {"domains": domains, "dimensions": payload.get("dimensions", []), "profile": payload.get("project_profile")}
    plan_id = canonical_digest(plan_body)
    plan = {
        "schema_version": SCHEMA_VERSION, "generated_at": now(),
        "snapshot_id": session["repository_identity"]["snapshot_id"], "plan_id": plan_id,
        "authored_by": "CODEX", **plan_body,
    }
    prior_coverage = read_json(out / "analysis_coverage.json", {})
    if prior_coverage.get("plan_id") != plan_id:
        coverage = {
            "schema_version": SCHEMA_VERSION, "snapshot_id": plan["snapshot_id"], "plan_id": plan_id,
            "domains": [{
                "domain_id": item["id"], "priority": item["priority"], "state": "PENDING",
                "reason": None, "completion_percent": 0, "inspected_references": [],
                "evidence_claim_ids": [], "findings_summary": None, "updated_at": now(),
            } for item in domains],
        }
    else:
        coverage = prior_coverage
    profile = read_json(out / "project_profile.json", {})
    if payload.get("project_profile") is not None:
        profile["codex_profile"] = payload["project_profile"]
        profile["provisional"] = False
        atomic_json(out / "project_profile.json", profile)
    atomic_json(out / "analysis_plan.json", plan)
    atomic_json(out / "analysis_coverage.json", coverage)
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    refresh_session(out)
    print(json.dumps({"plan_id": plan_id, "domains": len(domains)}, indent=2))
    return 0


def ingest(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    try:
        payload = load_payload(args.input)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    target = out / ("observed_evidence.json" if args.kind == "observed" else "interview_evidence.json")
    data = read_json(target, empty_store(args.kind))
    session = read_json(out / "session.json", {})
    incoming = [normalize_claim(item, args.kind, session["repository_identity"]["snapshot_id"]) for item in payload_claims(payload)]
    existing = [
        item.get("id")
        for name in ("observed_evidence.json", "interview_evidence.json", "evidence.json")
        for item in read_json(out / name, {"claims": []}).get("claims", [])
    ]
    assign_ids(incoming, existing)
    data.setdefault("claims", []).extend(incoming)
    if args.kind == "interview" and isinstance(payload, dict) and payload.get("question"):
        update = payload["question"]
        qid = update.get("id") or update.get("question_id")
        for question in data.setdefault("questions", []):
            if question["id"] == qid:
                question["answer"] = update.get("answer")
                question["status"] = update.get("status", "answered")
                question["answered_at"] = now()
                break
        if session.get("pending_question_id") == qid:
            session["pending_question_id"] = None
            session["interview_state"] = "IN_PROGRESS"
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at"] = now()
    atomic_json(target, data)
    refresh_session(out)
    print(json.dumps({"ingested": len(incoming), "ids": [item["id"] for item in incoming]}, indent=2))
    return 0


def update_coverage(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    payload = load_payload(args.input)
    updates = payload if isinstance(payload, list) else payload.get("domains", [payload])
    coverage = read_json(out / "analysis_coverage.json", {})
    plan = read_json(out / "analysis_plan.json", {})
    if not plan.get("plan_id") or coverage.get("plan_id") != plan.get("plan_id"):
        print("Coverage is not bound to a current analysis plan.", file=sys.stderr)
        return 2
    records = {item["domain_id"]: item for item in coverage.get("domains", [])}
    errors = []
    for update in updates:
        domain_id = update.get("domain_id")
        state = update.get("state")
        if domain_id not in records:
            errors.append(f"Unknown plan domain: {domain_id}")
            continue
        if state not in TERMINAL_COVERAGE:
            errors.append(f"{domain_id} must use a terminal coverage state.")
            continue
        reason = update.get("reason")
        references = list(update.get("inspected_references", []))
        evidence_ids = list(update.get("evidence_claim_ids", []))
        completion = update.get("completion_percent")
        if state == "COMPLETE" and not (references or evidence_ids):
            errors.append(f"{domain_id} COMPLETE requires inspected references or evidence IDs.")
        if state in {"PARTIAL", "BLOCKED"} and not reason:
            errors.append(f"{domain_id} {state} requires a reason.")
        if state == "PARTIAL" and (not isinstance(completion, int) or not 1 <= completion <= 99):
            errors.append(f"{domain_id} PARTIAL requires completion_percent from 1 to 99.")
        if state == "NOT_APPLICABLE" and not (reason and (references or evidence_ids)):
            errors.append(f"{domain_id} NOT_APPLICABLE requires a reason and supporting references.")
        if errors:
            continue
        records[domain_id].update({
            "state": state, "reason": reason, "completion_percent": 100 if state == "COMPLETE" else completion or 0,
            "inspected_references": references, "evidence_claim_ids": evidence_ids,
            "findings_summary": update.get("findings_summary"), "updated_at": now(),
        })
    if errors:
        print(json.dumps({"errors": errors}, indent=2), file=sys.stderr)
        return 2
    coverage["domains"] = list(records.values())
    coverage["updated_at"] = now()
    atomic_json(out / "analysis_coverage.json", coverage)
    session = read_json(out / "session.json", {})
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    session = refresh_session(out)
    print(json.dumps({"artifact_analysis_finished": session["artifact_analysis_finished"], "evidence_completeness": session["evidence_completeness"]}, indent=2))
    return 0


def active_claims(out: Path) -> list[dict[str, Any]]:
    claims = []
    for name in ("observed_evidence.json", "interview_evidence.json"):
        claims.extend(item for item in read_json(out / name, {"claims": []}).get("claims", []) if item.get("currency", "ACTIVE") == "ACTIVE")
    return claims


def set_gaps(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    session = refresh_session(out)
    if not session.get("artifact_analysis_finished"):
        print("All planned domains must reach a terminal state before gap selection.", file=sys.stderr)
        return 2
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    payload = load_payload(args.input)
    claims = {item["id"]: item for item in active_claims(out)}
    dimensions = []
    dimension_scores = {}
    errors = []
    for item in payload.get("dimensions", []):
        dimension_id = item.get("id")
        if dimension_id in dimension_scores:
            errors.append(f"Duplicate dimension ID: {dimension_id}")
        evidence_ids = list(item.get("evidence_claim_ids", []))
        linked = [claims[value] for value in evidence_ids if value in claims and dimension_id in claims[value].get("dimensions", [])]
        completeness = max((STATUS_COMPLETENESS.get(value["status"], 0) for value in linked), default=0)
        normalized = {
            "id": dimension_id, "topic": item.get("topic"), "relevant": bool(item.get("relevant", True)),
            "relevance_reason": item.get("relevance_reason"), "weight": int(item.get("weight", 1)),
            "resolution_channel": item.get("resolution_channel"), "evidence_claim_ids": [value["id"] for value in linked],
            "completeness_percent": completeness,
        }
        if not dimension_id or normalized["resolution_channel"] not in {"ARTIFACT", "INTERVIEW"}:
            errors.append("Each relevant dimension needs an ID and resolution channel.")
        if normalized["weight"] < 1:
            errors.append(f"Dimension {dimension_id} requires a positive weight.")
        dimensions.append(normalized)
        dimension_scores[dimension_id] = completeness
    gaps = []
    seen = set()
    for item in payload.get("gaps", []):
        dimension_id = item.get("dimension_id")
        if dimension_id not in dimension_scores:
            errors.append(f"Gap references unknown dimension {dimension_id}.")
            continue
        basis_ids = list(item.get("basis_claim_ids", []))
        basis_refs = list(item.get("basis_references", []))
        if not basis_ids and not basis_refs:
            errors.append(f"Gap {dimension_id} requires actual evidence/profile/coverage basis.")
        unknown = [value for value in basis_ids if value not in claims]
        if unknown:
            errors.append(f"Gap {dimension_id} references unknown claims: {unknown}")
        importance = int(item.get("importance", 0))
        if not 0 <= importance <= 100:
            errors.append(f"Gap {dimension_id} importance must be 0 through 100.")
        contradiction = bool(item.get("contradiction", False))
        confirm = bool(item.get("confirm_inference", False))
        score = round(importance * (100 - dimension_scores[dimension_id]) / 100 + (100 if contradiction else 0) + (20 if confirm else 0), 1)
        gap_id = item.get("id") or f"GAP-{canonical_digest([dimension_id, basis_ids, basis_refs])[:12].upper()}"
        if gap_id in seen:
            errors.append(f"Duplicate gap ID: {gap_id}")
        seen.add(gap_id)
        channel = next((value["resolution_channel"] for value in dimensions if value["id"] == dimension_id), None)
        relevant = next((value["relevant"] for value in dimensions if value["id"] == dimension_id), False)
        if not relevant:
            errors.append(f"Gap {dimension_id} cannot target a non-relevant dimension.")
        if item.get("resolution_channel") and item.get("resolution_channel") != channel:
            errors.append(f"Gap {dimension_id} routing disagrees with its dimension.")
        if not item.get("rationale"):
            errors.append(f"Gap {dimension_id} requires a Codex-authored rationale.")
        gaps.append({
            "id": gap_id, "topic": item.get("topic"), "dimension_id": dimension_id,
            "importance": importance, "completeness_percent": dimension_scores[dimension_id],
            "gap_score": score, "priority": "high" if score >= 75 else "medium" if score >= 40 else "low",
            "resolution_channel": channel, "basis_claim_ids": basis_ids,
            "basis_references": basis_refs, "rationale": item.get("rationale"),
            "contradiction": contradiction, "confirm_inference": confirm, "status": item.get("status", "open"),
            "authored_by": "CODEX",
        })
    if errors:
        print(json.dumps({"errors": errors}, indent=2), file=sys.stderr)
        return 2
    data = {
        "schema_version": SCHEMA_VERSION, "snapshot_id": session["repository_identity"]["snapshot_id"],
        "generated_at": now(), "dimensions": dimensions,
        "topics": topic_completeness(dimensions), "gaps": sorted(gaps, key=lambda value: (-value["gap_score"], value["id"])),
    }
    atomic_json(out / "gap_analysis.json", data)
    session = read_json(out / "session.json", {})
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    render_open_questions(out)
    print(json.dumps({"gaps": len(gaps), "highest_score": max((item["gap_score"] for item in gaps), default=None)}, indent=2))
    return 0


def topic_completeness(dimensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in dimensions:
        if item.get("relevant"):
            grouped[item.get("topic")].append(item)
    result = []
    for topic, items in grouped.items():
        denominator = sum(max(1, item["weight"]) for item in items)
        completeness = sum(item["completeness_percent"] * max(1, item["weight"]) for item in items) / denominator
        result.append({"topic": topic, "completeness_percent": round(completeness, 1), "dimension_ids": [item["id"] for item in items]})
    return sorted(result, key=lambda value: value["topic"] or "")


def queue_question(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    session = refresh_session(out)
    if not session.get("artifact_analysis_finished"):
        print("Artifact analysis is not finished.", file=sys.stderr)
        return 2
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    payload = load_payload(args.input)
    gaps = {item["id"]: item for item in read_json(out / "gap_analysis.json", {"gaps": []}).get("gaps", [])}
    gap = gaps.get(payload.get("gap_id"))
    if not gap or gap.get("resolution_channel") != "INTERVIEW" or gap.get("status", "open") != "open":
        print("Question must reference an active INTERVIEW gap.", file=sys.stderr)
        return 2
    if not payload.get("question") or not payload.get("rationale"):
        print("Codex-authored question and rationale are required.", file=sys.stderr)
        return 2
    if not gap.get("basis_claim_ids") and not gap.get("basis_references"):
        print("Question gap lacks project evidence basis.", file=sys.stderr)
        return 2
    data = read_json(out / "interview_evidence.json", empty_store("interview"))
    existing = next((item for item in data.get("questions", []) if item.get("gap_id") == gap["id"] and item.get("status") != "STALE"), None)
    question = {
        "id": payload.get("id") or f"Q-{canonical_digest([gap['id'], payload['question']])[:12].upper()}",
        "gap_id": gap["id"], "topic": gap.get("topic"), "dimension_id": gap.get("dimension_id"),
        "question": payload["question"], "rationale": payload["rationale"],
        "tentative_interpretation": payload.get("tentative_interpretation"),
        "basis_claim_ids": gap.get("basis_claim_ids", []), "basis_references": gap.get("basis_references", []),
        "gap_score": gap["gap_score"], "status": "open", "answer": None,
        "authored_by": "CODEX", "created_at": now(), "answered_at": None,
    }
    if existing:
        existing.update({key: value for key, value in question.items() if key not in {"id", "created_at"}})
        question = existing
    else:
        data.setdefault("questions", []).append(question)
    data["updated_at"] = now()
    atomic_json(out / "interview_evidence.json", data)
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    render_open_questions(out)
    print(json.dumps({"question_id": question["id"], "gap_score": question["gap_score"]}, indent=2))
    return 0


def next_question(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(json.dumps({"question": None, "reason": error}, indent=2))
        return 2
    session = refresh_session(out)
    if session.get("mode") == "static":
        print(json.dumps({"question": None, "reason": "Static mode does not conduct interviews."}, indent=2))
        return 0
    if not session.get("artifact_analysis_finished"):
        print(json.dumps({"question": None, "reason": "Artifact analysis still has PENDING domains."}, indent=2))
        return 2
    data = read_json(out / "interview_evidence.json", empty_store("interview"))
    if session.get("pending_question_id"):
        pending = next((item for item in data.get("questions", []) if item["id"] == session["pending_question_id"]), None)
        print(json.dumps({"question": pending, "resumed": True}, indent=2))
        return 0
    gaps = {item["id"]: item for item in read_json(out / "gap_analysis.json", {"gaps": []}).get("gaps", []) if item.get("status") == "open"}
    candidates = [item for item in data.get("questions", []) if item.get("status") == "open" and item.get("gap_id") in gaps]
    if not candidates:
        print(json.dumps({"question": None, "reason": "Codex has not queued a valuable unresolved interview question."}, indent=2))
        return 0
    question = sorted(candidates, key=lambda item: (-gaps[item["gap_id"]]["gap_score"], item["id"]))[0]
    question["status"] = "pending"
    question["gap_score"] = gaps[question["gap_id"]]["gap_score"]
    session["pending_question_id"] = question["id"]
    session["interview_state"] = "IN_PROGRESS"
    invalidate_session(session)
    atomic_json(out / "interview_evidence.json", data)
    atomic_json(out / "session.json", session)
    print(json.dumps({"question": question, "resumed": False}, indent=2))
    return 0


def set_reconciled(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    session = refresh_session(out)
    if not session.get("artifact_analysis_finished"):
        print("Artifact analysis must finish before reconciliation.", file=sys.stderr)
        return 2
    payload = load_payload(args.input)
    claims = [normalize_claim(item, "canonical", session["repository_identity"]["snapshot_id"]) for item in payload_claims(payload)]
    assign_ids(claims, [])
    atomic_json(out / "evidence.json", {"schema_version": SCHEMA_VERSION, "updated_at": now(), "authored_by": "CODEX", "claims": claims})
    session["reconciliation_ready"] = True
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    refresh_session(out)
    print(json.dumps({"canonical_claims": len(claims)}, indent=2))
    return 0


def write_outputs(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    session = read_json(out / "session.json", {})
    if not session.get("reconciliation_ready"):
        print("Codex reconciliation must be persisted before dossier generation.", file=sys.stderr)
        return 2
    payload = load_payload(args.input)
    if not isinstance(payload.get("project"), dict) or not isinstance(payload.get("dossier"), str) or not isinstance(payload.get("public_safe_summary"), str):
        print("Output payload requires project object, dossier text, and public_safe_summary text.", file=sys.stderr)
        return 2
    atomic_json(out / "project.json", payload["project"])
    atomic_text(out / "dossier.md", payload["dossier"].rstrip() + "\n")
    atomic_text(out / "public_safe_summary.md", payload["public_safe_summary"].rstrip() + "\n")
    session["outputs_ready"] = True
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    render_open_questions(out)
    refresh_session(out)
    print(json.dumps({"outputs_written": True}, indent=2))
    return 0


def set_interview_state(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, error = ensure_snapshot(project, out)
    if not ok:
        print(error, file=sys.stderr)
        return 2
    state = args.state.upper()
    if state not in INTERVIEW_STATES:
        print(f"Invalid interview state: {state}", file=sys.stderr)
        return 2
    session = read_json(out / "session.json", {})
    if session.get("pending_question_id") and state in {"COMPLETE", "NOT_APPLICABLE"}:
        print("Answer the pending question or stop with unknowns before closing the interview.", file=sys.stderr)
        return 2
    if session.get("pending_question_id") and state == "STOPPED_WITH_UNKNOWNS":
        data = read_json(out / "interview_evidence.json", empty_store("interview"))
        for question in data.get("questions", []):
            if question.get("id") == session["pending_question_id"]:
                question["status"] = "open"
        data["updated_at"] = now()
        atomic_json(out / "interview_evidence.json", data)
    session["interview_state"] = state
    if state in {"COMPLETE", "STOPPED_WITH_UNKNOWNS", "NOT_APPLICABLE"}:
        session["pending_question_id"] = None
    invalidate_session(session)
    atomic_json(out / "session.json", session)
    print(json.dumps(refresh_session(out), indent=2))
    return 0


def claim_errors(item: dict[str, Any], id_set: set[str], prefix: str) -> list[str]:
    errors = []
    claim_id = item.get("id", "<missing>")
    if not re.fullmatch(r"[A-Z]+-\d{3,}", str(claim_id)):
        errors.append(f"{prefix} invalid evidence ID: {claim_id}")
    if item.get("status") not in STATUSES:
        errors.append(f"{claim_id} uses invalid status {item.get('status')}")
    if item.get("currency", "ACTIVE") not in CURRENCIES:
        errors.append(f"{claim_id} uses invalid currency {item.get('currency')}")
    sources = item.get("sources", [])
    if item.get("status") not in {"UNKNOWN", "USER_CONFIRMATION_REQUIRED"} and not sources:
        errors.append(f"{claim_id} has no provenance")
    for source in sources:
        if source.get("type") not in SOURCE_TYPES:
            errors.append(f"{claim_id} uses invalid source type {source.get('type')}")
        if source.get("type") == "VIDEO" and source.get("timestamp_seconds") is None:
            errors.append(f"{claim_id} describes video behavior without a timestamp")
        if source.get("type") in {"VIDEO", "SCREENSHOT"} and source.get("cached_path") and source.get("reference") == source.get("cached_path"):
            errors.append(f"{claim_id} uses a cached path as media provenance")
        reference = str(source.get("reference", ""))
        if source.get("type") in {"VIDEO", "SCREENSHOT"} and re.search(r"(^|/)\.repo-portfolio/media/cache/|^media/cache/", reference):
            errors.append(f"{claim_id} uses a cached path as media provenance")
        if is_sensitive(reference) and (not item.get("sensitive") or item.get("public_safe")):
            errors.append(f"{claim_id} references a sensitive path without sensitive handling")
    if item.get("status") == "USER_ESTIMATE" and any(source.get("type") != "USER_ESTIMATE" for source in sources):
        errors.append(f"{claim_id} user estimate has non-estimate provenance")
    if item.get("category") == "ownership" and item.get("status") in {"CONFIRMED", "USER_CONFIRMED"}:
        source_types = {source.get("type") for source in sources}
        if re.search(r"\b(owned|built|designed|responsible)\b", item.get("claim", ""), re.I) and not source_types & {"USER_ATTESTATION", "DOCUMENTATION"}:
            errors.append(f"{claim_id} makes a personal ownership claim without suitable support")
    if {source.get("type") for source in sources} <= ARTIFACT_SOURCES and re.search(
        r"\b(tests? pass(?:ed|ing)?|installer works?|application (?:runs?|launches?)|deployment succeeds?)\b",
        item.get("claim", ""), re.I,
    ):
        errors.append(f"{claim_id} asserts runtime behavior from static evidence")
    if item.get("status") == "CONTRADICTED" and not item.get("contradicts"):
        errors.append(f"{claim_id} is contradicted without a contradiction relationship")
    for related in item.get("supports", []) + item.get("contradicts", []):
        if related not in id_set:
            errors.append(f"{claim_id} references unknown related claim {related}")
    return errors


def validation_errors(out: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for relative in REQUIRED_OUTPUTS:
        if not (out / relative).is_file():
            errors.append(f"Missing required artifact: {relative}")
    for relative in REQUIRED_DIRECTORIES:
        if not (out / relative).is_dir():
            errors.append(f"Missing required artifact directory: {relative}")
    names = [
        "project.json", "observed_evidence.json", "interview_evidence.json", "evidence.json",
        "session.json", "project_profile.json", "analysis_plan.json", "analysis_coverage.json",
        "gap_analysis.json", "media/media_index.json",
    ]
    parsed = {}
    for name in names:
        if not (out / name).exists():
            errors.append(f"Missing required state artifact: {name}")
            continue
        value = read_json(out / name, None)
        if value is None:
            errors.append(f"Malformed JSON: {name}")
        else:
            parsed[name] = value
    session = parsed.get("session.json", {})
    plan = parsed.get("analysis_plan.json", {})
    coverage = parsed.get("analysis_coverage.json", {})
    if not plan.get("plan_id"):
        errors.append("No Codex-authored dynamic analysis plan has been persisted.")
    if plan.get("authored_by") != "CODEX":
        errors.append("The dynamic analysis plan is not marked as Codex-authored.")
    if coverage.get("plan_id") != plan.get("plan_id") or coverage.get("snapshot_id") != plan.get("snapshot_id"):
        errors.append("Analysis coverage is not bound to the current plan and snapshot.")
    plan_ids = {item.get("id") for item in plan.get("domains", [])}
    coverage_by_id = {item.get("domain_id"): item for item in coverage.get("domains", [])}
    if set(coverage_by_id) != plan_ids:
        errors.append("Coverage domains do not exactly match planned domains.")
    for domain_id in plan_ids:
        record = coverage_by_id.get(domain_id, {})
        state = record.get("state")
        if state == "PENDING" or state not in TERMINAL_COVERAGE:
            errors.append(f"Planned domain {domain_id} remains PENDING or invalid.")
        if state in {"PARTIAL", "BLOCKED"} and not record.get("reason"):
            errors.append(f"{domain_id} {state} lacks a reason.")
        if state == "PARTIAL" and not 1 <= record.get("completion_percent", 0) <= 99:
            errors.append(f"{domain_id} PARTIAL has invalid completion percentage.")
        if state == "NOT_APPLICABLE" and not (record.get("reason") and (record.get("inspected_references") or record.get("evidence_claim_ids"))):
            errors.append(f"{domain_id} NOT_APPLICABLE lacks justification.")
        if state in {"PARTIAL", "BLOCKED"}:
            warnings.append(f"Coverage limitation: {domain_id} is {state}: {record.get('reason')}")
    observed = parsed.get("observed_evidence.json", {}).get("claims", [])
    interview = parsed.get("interview_evidence.json", {}).get("claims", [])
    canonical = parsed.get("evidence.json", {}).get("claims", [])
    all_ids = [item.get("id") for item in observed + interview + canonical]
    for layer_name, layer_claims in (("observed", observed), ("interview", interview), ("canonical", canonical)):
        duplicates = [
            value for value in {item.get("id") for item in layer_claims}
            if value and sum(item.get("id") == value for item in layer_claims) > 1
        ]
        if duplicates:
            errors.append(f"Duplicate {layer_name} evidence IDs: {duplicates}")
    source_duplicates = sorted({item.get("id") for item in observed} & {item.get("id") for item in interview})
    if source_duplicates:
        errors.append(f"Evidence IDs collide across observed and interview stores: {source_duplicates}")
    id_set = set(value for value in all_ids if value)
    source_layer_ids = {item.get("id") for item in observed + interview if item.get("id")}
    for domain_id, record in coverage_by_id.items():
        unknown_ids = [value for value in record.get("evidence_claim_ids", []) if value not in source_layer_ids]
        if unknown_ids:
            errors.append(f"Coverage domain {domain_id} references unknown evidence IDs: {unknown_ids}")
    for prefix, claims in (("observed", observed), ("interview", interview), ("canonical", canonical)):
        for item in claims:
            errors.extend(claim_errors(item, id_set, prefix))
    active_inputs = [item for item in observed + interview if item.get("currency", "ACTIVE") == "ACTIVE"]
    represented = set()
    canonical_by_id = {}
    for item in canonical:
        canonical_by_id[item["id"]] = item
        represented.add(item["id"])
        represented.update(item.get("derived_from_claim_ids", []))
    for item in active_inputs:
        if item["id"] not in represented:
            errors.append(f"Active source-layer claim {item['id']} is absent from Codex reconciliation.")
    input_by_id = {item["id"]: item for item in active_inputs}
    for item in canonical:
        derived_ids = list(item.get("derived_from_claim_ids", []))
        if item.get("id") in input_by_id and item.get("id") not in derived_ids:
            derived_ids.append(item["id"])
        derived = [input_by_id[value] for value in derived_ids if value in input_by_id]
        source_keys = {json.dumps(source, sort_keys=True) for source in item.get("sources", [])}
        for source_claim in derived:
            for source in source_claim.get("sources", []):
                if json.dumps(source, sort_keys=True) not in source_keys:
                    errors.append(f"Canonical claim {item['id']} drops provenance from {source_claim['id']}.")
            if source_claim.get("status") == "USER_ESTIMATE" and item.get("status") != "USER_ESTIMATE":
                errors.append(f"Canonical claim {item['id']} promotes user estimate {source_claim['id']}.")
    project_data = parsed.get("project.json", {})
    if project_data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"project.json must declare schema_version {SCHEMA_VERSION}.")
    missing_core = [key for key in CORE_KEYS if key not in project_data]
    if missing_core:
        errors.append(f"project.json is missing universal core keys: {', '.join(missing_core)}")
    semantic_summary = project_data.get("semantic_summary")
    if not isinstance(semantic_summary, dict):
        errors.append("project.json requires a semantic_summary object.")
        semantic_summary = {}
    elif canonical and not any(isinstance(entries, list) and entries for entries in semantic_summary.values()):
        errors.append("project.json semantic_summary must represent canonical project evidence.")
    active_canonical = {item["id"]: item for item in canonical if item.get("currency", "ACTIVE") == "ACTIVE"}
    for section, entries in semantic_summary.items():
        if not isinstance(entries, list):
            errors.append(f"semantic_summary.{section} must be a list.")
            continue
        for entry in entries:
            if not isinstance(entry.get("statement"), str) or not entry["statement"].strip():
                errors.append(f"Semantic summary entry in {section} lacks a statement.")
            if not isinstance(entry.get("dimensions"), list):
                errors.append(f"Semantic summary entry in {section} lacks dimensions.")
            evidence_ids = entry.get("evidence_claim_ids", [])
            if not evidence_ids or any(value not in active_canonical for value in evidence_ids):
                errors.append(f"Semantic summary entry in {section} is not traceable to active canonical evidence.")
            statuses = {active_canonical[value]["status"] for value in evidence_ids if value in active_canonical}
            if entry.get("status") not in statuses:
                errors.append(f"Semantic summary entry in {section} exceeds or disagrees with linked evidence status.")
    dossier = (out / "dossier.md").read_text(encoding="utf-8") if (out / "dossier.md").exists() else ""
    for claim_id in active_canonical:
        if claim_id not in dossier:
            errors.append(f"Dossier omits active canonical evidence {claim_id}.")
    public = (out / "public_safe_summary.md").read_text(encoding="utf-8") if (out / "public_safe_summary.md").exists() else ""
    for claim_id in set(re.findall(r"\b[A-Z]+-\d{3,}\b", public)):
        item = active_canonical.get(claim_id)
        if not item or not item.get("public_safe") or item.get("sensitive") or item.get("status") not in {"CONFIRMED", "USER_CONFIRMED"}:
            errors.append(f"Public summary contains unsafe or unsupported claim {claim_id}.")
    questions = parsed.get("interview_evidence.json", {}).get("questions", [])
    if sum(item.get("status") == "pending" for item in questions) > 1:
        errors.append("More than one interview question is pending.")
    gaps = {item["id"]: item for item in parsed.get("gap_analysis.json", {}).get("gaps", [])}
    for question in questions:
        gap = gaps.get(question.get("gap_id"))
        if question.get("status") != "STALE" and (not gap or gap.get("resolution_channel") != "INTERVIEW"):
            errors.append(f"Question {question.get('id')} is not linked to an INTERVIEW gap.")
        if question.get("authored_by") != "CODEX" or not question.get("rationale"):
            errors.append(f"Question {question.get('id')} lacks Codex authorship or rationale.")
    media = parsed.get("media/media_index.json", {})
    for item in media.get("items", []):
        original_url = item.get("original_url")
        if original_url:
            if item.get("source") != original_url:
                errors.append(f"Remote media {item.get('id')} does not preserve its original URL as canonical source.")
            cached_path = item.get("cached_path")
            if item.get("type") != "unavailable" and (not cached_path or not str(cached_path).startswith("media/cache/")):
                errors.append(f"Remote media {item.get('id')} is not cached inside the analysis directory.")
            elif item.get("type") != "unavailable" and not (out / str(cached_path)).is_file():
                errors.append(f"Remote media {item.get('id')} cached file is missing.")
        for frame in item.get("frames", []):
            if frame.get("source") != item.get("source") or frame.get("timestamp_seconds") is None:
                errors.append(f"Video frame for {item.get('id')} lacks canonical source or timestamp provenance.")
            if not frame.get("path") or not (out / str(frame.get("path"))).is_file():
                errors.append(f"Video frame for {item.get('id')} is missing from the analysis directory.")
    return errors, warnings


def validate(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    ok, snapshot_error = ensure_snapshot(project, out)
    errors, warnings = validation_errors(out)
    if not ok:
        errors.append(snapshot_error or "Repository snapshot mismatch.")
    session = refresh_session(out)
    artifact_finished = bool(session.get("artifact_analysis_finished"))
    contract_valid = not errors
    required_present = all((out / relative).is_file() for relative in REQUIRED_OUTPUTS) and all(
        (out / relative).is_dir() for relative in REQUIRED_DIRECTORIES
    )
    interview_terminal = session.get("interview_state") in {"COMPLETE", "STOPPED_WITH_UNKNOWNS", "NOT_APPLICABLE"} or session.get("mode") == "static"
    workflow_complete = bool(
        contract_valid and artifact_finished and interview_terminal and required_present
        and session.get("reconciliation_ready") and session.get("outputs_ready")
    )
    if contract_valid:
        session["validated_revision"] = session.get("state_revision")
    session["workflow_complete"] = workflow_complete
    session["phase"] = "complete" if workflow_complete else session.get("phase", "artifact_analysis")
    atomic_json(out / "session.json", session)
    result = {
        "valid": contract_valid and artifact_finished and workflow_complete,
        "contract_valid": contract_valid, "artifact_analysis_finished": artifact_finished,
        "evidence_completeness": session.get("evidence_completeness", 0.0),
        "workflow_complete": workflow_complete, "errors": errors, "warnings": warnings,
        "validated_at": now(),
    }
    atomic_json(out / "validation.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


def finalize(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    render_open_questions(out)
    session = refresh_session(out)
    print(json.dumps({
        "artifact_analysis_finished": session["artifact_analysis_finished"],
        "evidence_completeness": session["evidence_completeness"],
        "workflow_complete": session["workflow_complete"],
    }, indent=2))
    return 0


def doctor(_: argparse.Namespace) -> int:
    result = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "minimum_python": ".".join(map(str, MIN_PYTHON)),
        "python_supported": sys.version_info >= MIN_PYTHON,
        "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
        "yt_dlp": shutil.which("yt-dlp"),
        "remote_direct_media": True,
        "youtube_media": bool(shutil.which("yt-dlp")),
    }
    print(json.dumps(result, indent=2))
    return 0 if result["python_supported"] else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Deterministic infrastructure for the Repo-Portfolio Codex skill.")
    root.add_argument("--version", action="version", version=f"Repo-Portfolio {SCHEMA_VERSION}")
    commands = root.add_subparsers(dest="command", required=True)
    analyze_parser = commands.add_parser("analyze")
    analyze_parser.add_argument("project")
    analyze_parser.add_argument("--output")
    analyze_parser.add_argument("--media", action="append", default=[])
    analyze_parser.add_argument("--deep", action="store_true")
    analyze_parser.add_argument("--static", action="store_true")
    analyze_parser.set_defaults(handler=analyze)
    input_commands = {
        "set-plan": set_plan, "update-coverage": update_coverage, "set-gaps": set_gaps,
        "queue-question": queue_question, "set-reconciled": set_reconciled, "write-outputs": write_outputs,
    }
    for name, handler in input_commands.items():
        command = commands.add_parser(name)
        command.add_argument("project")
        command.add_argument("--output")
        command.add_argument("--input", required=True)
        command.set_defaults(handler=handler)
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("project")
    ingest_parser.add_argument("--output")
    ingest_parser.add_argument("--kind", choices=("observed", "interview"), required=True)
    ingest_parser.add_argument("--input", required=True)
    ingest_parser.set_defaults(handler=ingest)
    for name, handler in (("next-question", next_question), ("finalize", finalize), ("validate", validate)):
        command = commands.add_parser(name)
        command.add_argument("project")
        command.add_argument("--output")
        command.set_defaults(handler=handler)
    state_parser = commands.add_parser("set-interview-state")
    state_parser.add_argument("project")
    state_parser.add_argument("--output")
    state_parser.add_argument("--state", required=True)
    state_parser.set_defaults(handler=set_interview_state)
    doctor_parser = commands.add_parser("doctor")
    doctor_parser.set_defaults(handler=doctor)
    return root


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"Repo-Portfolio requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; found {sys.version.split()[0]}.", file=sys.stderr)
        return 2
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"Invalid state or payload: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
