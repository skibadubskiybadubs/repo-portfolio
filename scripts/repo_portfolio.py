#!/usr/bin/env python3
"""Deterministic support pipeline for the Repo-Portfolio Codex skill.

This helper only performs static reads of target projects. It never imports project
modules, installs dependencies, or executes project-owned commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
OUTPUT_NAME = ".repo-portfolio"
STATUSES = {
    "CONFIRMED",
    "USER_CONFIRMED",
    "USER_ESTIMATE",
    "STRONG_INFERENCE",
    "WEAK_INFERENCE",
    "USER_CONFIRMATION_REQUIRED",
    "UNKNOWN",
    "CONTRADICTED",
}
SOURCE_TYPES = {
    "SOURCE_CODE",
    "TEST",
    "CONFIG",
    "BUILD_OR_PACKAGE_METADATA",
    "GIT_HISTORY",
    "DOCUMENTATION",
    "SCREENSHOT",
    "VIDEO",
    "USER_ATTESTATION",
    "USER_ESTIMATE",
    "INFERENCE",
}
ARTIFACT_SOURCES = SOURCE_TYPES - {"USER_ATTESTATION", "USER_ESTIMATE"}
USER_SOURCES = {"USER_ATTESTATION", "USER_ESTIMATE"}
CORE_KEYS = [
    "project",
    "problem",
    "users",
    "workflows",
    "technology",
    "architecture",
    "automation",
    "testing",
    "delivery",
    "maintenance",
    "ownership",
    "impact",
    "decisions",
    "career_signals",
    "unknowns",
    "extensions",
]
REQUIRED_OUTPUTS = [
    "dossier.md",
    "project.json",
    "observed_evidence.json",
    "interview_evidence.json",
    "evidence.json",
    "open_questions.md",
    "public_safe_summary.md",
    "media/media_index.json",
]
IGNORED_DIRS = {
    ".git",
    OUTPUT_NAME,
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
}
TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".jsx", ".json", ".kt", ".kts", ".lua", ".md",
    ".php", ".pl", ".ps1", ".py", ".r", ".rb", ".rs", ".scala",
    ".sh", ".sql", ".swift", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml", ".vue", ".svelte", ".gradle", ".properties",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
LANGUAGE_EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".cs": "C#",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".go": "Go",
    ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++",
    ".hpp": "C++", ".r": "R", ".scala": "Scala", ".lua": "Lua",
    ".sh": "Shell", ".ps1": "PowerShell", ".sql": "SQL",
    ".html": "HTML", ".css": "CSS", ".vue": "Vue", ".svelte": "Svelte",
}
MANIFEST_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile",
    "poetry.lock", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "pom.xml", "build.gradle",
    "build.gradle.kts", "gemfile", "composer.json", "mix.exs", "pubspec.yaml",
    "cmakelists.txt", "makefile", "dockerfile",
}
SENSITIVE_NAME_RE = re.compile(
    r"(^|[._-])(secret|credential|token|password|private|customer|client-data)([._-]|$)|"
    r"(^|/)(\.env($|\.)|id_rsa|id_ed25519|.*\.pem$|.*\.key$)", re.I
)
CATEGORY_PREFIX = {
    "project": "PROJ", "product": "PROD", "problem": "PROB", "users": "USER",
    "workflow": "FLOW", "previous_workflow": "PREV", "automation": "AUTO",
    "domain": "DOMAIN", "architecture": "ARCH", "interface": "UX",
    "integration": "INT", "testing": "TEST", "reliability": "REL",
    "performance": "PERF", "installation": "INST", "delivery": "DELIV",
    "configuration": "CONF", "maintenance": "MAINT", "git_history": "GIT",
    "decisions": "DEC", "constraints": "CONST", "ownership": "OWN",
    "impact": "IMPACT", "technology": "TECH", "documentation": "DOC",
    "media": "MEDIA",
}
DOSSIER_SECTIONS = [
    ("Project Overview", {"project", "product"}),
    ("Evidence Confidence Summary", set()),
    ("Problem / Motivation", {"problem"}),
    ("Users / Stakeholders", {"users"}),
    ("Previous Workflow", {"previous_workflow"}),
    ("Current Workflow", {"workflow"}),
    ("Automation", {"automation"}),
    ("Encoded Domain / Business Rules", {"domain"}),
    ("Architecture", {"architecture"}),
    ("Interfaces / UX", {"interface"}),
    ("Integrations", {"integration"}),
    ("Testing / QA", {"testing"}),
    ("Reliability", {"reliability"}),
    ("Performance", {"performance"}),
    ("Installation / Distribution", {"installation"}),
    ("Deployment", {"delivery"}),
    ("Configuration", {"configuration"}),
    ("Maintenance / Evolution", {"maintenance"}),
    ("Git History Summary", {"git_history"}),
    ("Important Engineering Decisions", {"decisions"}),
    ("Constraints / Tradeoffs", {"constraints"}),
    ("Personal Ownership", {"ownership"}),
    ("Impact / Outcomes", {"impact"}),
    ("Technologies", {"technology"}),
    ("Engineering Practices Demonstrated", {"testing", "reliability", "delivery", "documentation"}),
    ("Career Signals", set()),
    ("Evidence Index", set()),
    ("Remaining Unknowns", set()),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=False)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def output_dir(project: Path, explicit: str | None = None) -> Path:
    return Path(explicit).expanduser().resolve() if explicit else project / OUTPUT_NAME


def safe_reference(path: Path, project: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project.resolve()).as_posix()
    except ValueError:
        digest = hashlib.sha256(str(resolved.parent).encode()).hexdigest()[:8]
        return f"external:{digest}/{resolved.name}"


def is_sensitive_reference(reference: str) -> bool:
    return bool(SENSITIVE_NAME_RE.search(reference.replace("\\", "/")))


def run_readonly(args: list[str], cwd: Path, timeout: int = 15) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"},
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def classify_kind(relative: str, suffix: str) -> str:
    lowered = relative.lower()
    name = Path(lowered).name
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if "test" in Path(lowered).parts or re.search(r"(^|[._-])(test|spec)([._-]|$)", name):
        return "test"
    if lowered.startswith(".github/workflows/") or any(x in name for x in ("gitlab-ci", "jenkinsfile", "azure-pipelines")):
        return "ci"
    if name in MANIFEST_NAMES or suffix in {".csproj", ".sln", ".fsproj"}:
        return "build_or_package"
    if name.startswith("readme") or name.startswith("changelog") or name.startswith("contributing") or lowered.startswith("docs/"):
        return "documentation"
    if any(x in lowered for x in ("install", "setup", "deploy", "docker", "helm", "terraform")):
        return "delivery"
    if suffix in {".json", ".toml", ".yaml", ".yml", ".xml", ".ini", ".cfg", ".properties"}:
        return "config"
    if suffix in LANGUAGE_EXTENSIONS:
        return "source"
    return "other"


def inventory_project(project: Path, deep: bool) -> dict[str, Any]:
    limit = 50000 if deep else 12000
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    truncated = False
    for root, dirs, files in os.walk(project, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(
            d for d in dirs
            if d.lower() not in IGNORED_DIRS
            and not (root_path / d).is_symlink()
        )
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
            entries.append({
                "path": relative,
                "extension": suffix,
                "size": stat.st_size,
                "kind": classify_kind(relative, suffix),
                "sensitive_name": is_sensitive_reference(relative),
            })
            if len(entries) >= limit:
                truncated = True
                warnings.append(f"Inventory capped at {limit} files; use --deep for a larger scan budget.")
                break
        if truncated:
            break
    kinds = Counter(entry["kind"] for entry in entries)
    extensions = Counter(entry["extension"] for entry in entries if entry["extension"])
    fingerprint_input = "\n".join(f"{e['path']}:{e['size']}" for e in entries)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "project_root": str(project),
        "file_count": len(entries),
        "truncated": truncated,
        "fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        "counts_by_kind": dict(sorted(kinds.items())),
        "counts_by_extension": dict(extensions.most_common()),
        "files": entries,
        "warnings": warnings,
    }


def sample_text(project: Path, entry: dict[str, Any], max_bytes: int = 65536) -> str:
    if entry["sensitive_name"] or entry["size"] > 2_000_000:
        return ""
    if entry["extension"] not in TEXT_EXTENSIONS and entry["kind"] not in {"documentation", "build_or_package", "ci"}:
        return ""
    try:
        return (project / entry["path"]).read_bytes()[:max_bytes].decode("utf-8", errors="ignore")
    except OSError:
        return ""


def discover_profile(project: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    entries = inventory["files"]
    paths = {entry["path"].lower(): entry for entry in entries}
    names = {Path(path).name for path in paths}
    language_counts = Counter()
    for entry in entries:
        language = LANGUAGE_EXTENSIONS.get(entry["extension"])
        if language and entry["kind"] in {"source", "test"}:
            language_counts[language] += 1

    manifest_entries = [e for e in entries if e["kind"] == "build_or_package"]
    selected = [e for e in manifest_entries if e["size"] < 2_000_000][:80]
    selected.extend(
        e for e in entries
        if e["kind"] in {"source", "test"} and e["size"] < 2_000_000
    )
    selected = selected[:160]
    combined = "\n".join(sample_text(project, e) for e in selected).lower()
    path_blob = "\n".join(paths)
    ecosystems: list[str] = []
    project_types: list[str] = []
    probable_domains: list[str] = []

    def add(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)

    if any(n in names for n in ("pyproject.toml", "setup.py", "requirements.txt", "pipfile")) or language_counts["Python"]:
        add(ecosystems, "Python")
    if "package.json" in names or language_counts["JavaScript"] or language_counts["TypeScript"]:
        add(ecosystems, "Node.js")
    if any(e["extension"] in {".csproj", ".sln", ".fsproj"} for e in entries):
        add(ecosystems, ".NET")
    if "cargo.toml" in names:
        add(ecosystems, "Rust")
    if "go.mod" in names:
        add(ecosystems, "Go")
    if "pom.xml" in names or "build.gradle" in names or "build.gradle.kts" in names:
        add(ecosystems, "JVM")
    if re.search(r"grasshopper|rhino(common)?", combined + path_blob):
        add(ecosystems, "Rhino/Grasshopper")
        add(project_types, "host_application_plugin")
        add(probable_domains, "AEC/computational_design")
    if re.search(r"autodesk\.revit|revitapi|dynamo", combined + path_blob):
        add(ecosystems, "Revit/Dynamo")
        add(project_types, "host_application_plugin")
        add(probable_domains, "AEC/BIM")
    if re.search(r"react|next\.js|vue|angular|svelte", combined) or any(e["extension"] in {".tsx", ".jsx", ".vue", ".svelte"} for e in entries):
        add(project_types, "web_application")
    if re.search(r"fastapi|django|flask|express|nestjs|spring-boot|aspnet", combined):
        add(project_types, "service_or_web_backend")
    if any(re.search(r"(^|/)(cli|commands?)(/|\.|$)", p) for p in paths) or re.search(r"argparse|click|typer|commander|clap::", combined):
        add(project_types, "command_line_tool")
    if any("plugin" in p or "extension" in p for p in paths):
        add(project_types, "plugin_or_extension")
    if any(e["extension"] in {".ipynb", ".r"} for e in entries) or re.search(r"pandas|numpy|scipy|jupyter|tidyverse", combined):
        add(project_types, "data_or_research_tool")
    if any(Path(p).name in {"lib", "library"} for p in paths) or re.search(r"\[project\]|\"main\"\s*:|\"exports\"\s*:", combined):
        add(project_types, "library_or_package")
    if not project_types:
        add(project_types, "unknown_software_project")
    if not ecosystems:
        add(ecosystems, "Unknown/mixed")

    capabilities = {
        "ui": any(e["extension"] in {".html", ".css", ".jsx", ".tsx", ".vue", ".svelte", ".xaml"} for e in entries) or "host_application_plugin" in project_types,
        "api": bool(re.search(r"openapi|swagger|routes?|controllers?|graphql", combined + path_blob)),
        "database": bool(re.search(r"postgres|mysql|sqlite|mongodb|entityframework|sqlalchemy|prisma|migrations?", combined + path_blob)),
        "automation": bool(re.search(r"automation|workflow|batch|pipeline|scheduler|generate|transform", combined + path_blob)),
        "installer": any(e["kind"] == "delivery" and "install" in e["path"].lower() for e in entries),
        "tests": any(e["kind"] == "test" for e in entries),
        "git_history": (project / ".git").exists(),
        "media": any(e["kind"] in {"image", "video"} for e in entries),
        "ci": any(e["kind"] == "ci" for e in entries),
        "deployment": any(e["kind"] == "delivery" and any(x in e["path"].lower() for x in ("deploy", "docker", "helm", "terraform")) for e in entries),
        "documentation": any(e["kind"] == "documentation" for e in entries),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "provisional": True,
        "project_types": project_types,
        "ecosystems": ecosystems,
        "languages": [{"name": name, "file_count": count} for name, count in language_counts.most_common()],
        "probable_domains": probable_domains,
        "capabilities": capabilities,
        "signals": {
            "manifests": [e["path"] for e in manifest_entries],
            "top_level": sorted({e["path"].split("/", 1)[0] for e in entries})[:100],
        },
    }


def make_plan(profile: dict[str, Any], deep: bool) -> dict[str, Any]:
    caps = profile["capabilities"]
    types = set(profile["project_types"])
    domains: list[dict[str, Any]] = []

    def domain(name: str, priority: str, reason: str, focus: list[str]) -> None:
        domains.append({"domain": name, "priority": priority, "reason": reason, "focus": focus})

    domain("product_and_purpose", "high", "Required to establish what the project demonstrably does.", ["entry points", "inputs", "outputs", "documented workflows"])
    domain("architecture", "high", "Required for every software project.", ["components", "boundaries", "data flow", "state", "extension points"])
    if caps["automation"] or types & {"host_application_plugin", "data_or_research_tool", "command_line_tool"}:
        domain("automation_and_domain_logic", "high", "Workflow or transformation signals were discovered.", ["manual steps encoded", "rules", "validation", "orchestration", "human intervention"])
    if caps["ui"]:
        domain("interface_and_ux", "medium", "User-interface or host-application integration was detected.", ["interaction flow", "feedback", "errors", "configuration", "visual outputs"])
    if caps["api"] or caps["database"]:
        domain("interfaces_and_data", "high", "API or persistence signals were detected.", ["API surface", "data model", "authentication", "integrations", "transactions"])
    if caps["tests"]:
        domain("testing_and_qa", "high", "Test artifacts exist.", ["test levels", "asserted behavior", "fixtures", "CI invocation"])
    if caps["installer"] or caps["deployment"] or caps["ci"]:
        domain("delivery", "medium", "Installation, deployment, or CI assets exist.", ["packaging", "compatibility", "configuration", "release/deployment path"])
    domain("reliability_and_maintenance", "medium", "Reliability and maintainability are cross-cutting evidence domains.", ["validation", "errors", "logging", "fallbacks", "maintenance seams"])
    if caps["git_history"]:
        domain("git_history", "high", "Git metadata is available.", ["lifespan", "contributors", "evolution", "releases", "refactors", "test growth"])
    if caps["media"]:
        domain("media", "medium", "Screenshots or videos are available.", ["visible workflow", "UI", "outputs", "errors", "timestamps"])
    if "host_application_plugin" in types:
        domain("host_ecosystem", "high", "Host-application integration was detected.", ["host API", "version compatibility", "installation", "model operations", "domain constraints"])
    if "web_application" in types or "service_or_web_backend" in types:
        domain("web", "high", "Web application components were detected.", ["frontend/backend split", "routes", "data model", "auth", "deployment"])
    if "unknown_software_project" in types:
        domain("unknown_ecosystem_brief", "high", "No known project archetype was reliable.", ["manifests", "largest source clusters", "entry-like symbols", "dependency conventions", "sample tests"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "mode": "deep" if deep else "standard",
        "methodology": "fixed evidence rules with adaptive technical investigation",
        "domains": domains,
        "explicitly_skipped": [
            name for name, relevant in {
                "web_specific": bool(types & {"web_application", "service_or_web_backend"}),
                "host_application_specific": "host_application_plugin" in types,
                "database_specific": caps["database"],
                "media_specific": caps["media"],
            }.items() if not relevant
        ],
    }


def git_summary(project: Path) -> dict[str, Any]:
    code, _, _ = run_readonly(["git", "rev-parse", "--is-inside-work-tree"], project)
    if code != 0:
        return {"available": False, "warnings": ["No readable Git work tree was found."]}
    _, root, _ = run_readonly(["git", "rev-parse", "--show-toplevel"], project)
    _, log, log_err = run_readonly([
        "git", "log", "--date=iso-strict", "--pretty=format:%H%x09%aI%x09%an%x09%ae%x09%s", "-n", "5000"
    ], project, timeout=30)
    commits = []
    for line in log.splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5:
            commits.append({"hash": parts[0], "date": parts[1], "author": parts[2], "email": parts[3], "subject": parts[4]})
    contributors = Counter((c["author"], c["email"]) for c in commits)
    _, tags, _ = run_readonly(["git", "tag", "--list"], project)
    return {
        "available": True,
        "repository_root": root,
        "commit_count_scanned": len(commits),
        "first_commit_date": commits[-1]["date"] if commits else None,
        "latest_commit_date": commits[0]["date"] if commits else None,
        "contributors": [
            {"name": name, "email": email, "commits_scanned": count}
            for (name, email), count in contributors.most_common()
        ],
        "tags": tags.splitlines()[:500] if tags else [],
        "recent_commits": commits[:100],
        "warnings": [log_err] if log_err and not commits else [],
    }


def ffprobe(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    executable = shutil.which("ffprobe")
    if not executable:
        return None, "ffprobe is unavailable; video metadata was not extracted."
    code, out, err = run_readonly([
        executable, "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height",
        "-of", "json", str(path)
    ], path.parent, timeout=30)
    if code:
        return None, f"ffprobe failed for {path.name}: {err or 'unknown error'}"
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, f"ffprobe returned malformed metadata for {path.name}."


def extract_frames(path: Path, destination: Path) -> tuple[list[dict[str, Any]], str | None]:
    executable = shutil.which("ffmpeg")
    if not executable:
        return [], "ffmpeg is unavailable; representative frames were not extracted."
    destination.mkdir(parents=True, exist_ok=True)
    for derived in destination.glob("*.jpg"):
        derived.unlink()
    pattern = destination / "scene-%03d.jpg"
    command = [
        executable, "-y", "-v", "error", "-i", str(path), "-vf",
        "select='gt(scene,0.35)',scale='min(1600,iw)':-2", "-vsync", "vfr",
        "-frames:v", "12", str(pattern),
    ]
    code, _, err = run_readonly(command, path.parent, timeout=90)
    frames = sorted(destination.glob("scene-*.jpg"))
    if code or not frames:
        pattern = destination / "periodic-%03d.jpg"
        command = [
            executable, "-y", "-v", "error", "-i", str(path), "-vf",
            "fps=1/30,scale='min(1600,iw)':-2", "-frames:v", "12", str(pattern),
        ]
        code, _, err = run_readonly(command, path.parent, timeout=90)
        frames = sorted(destination.glob("periodic-*.jpg"))
    if code and not frames:
        return [], f"ffmpeg failed for {path.name}: {err or 'unknown error'}"
    return [
        {"path": frame.as_posix(), "sequence": index + 1, "timestamp": None}
        for index, frame in enumerate(frames)
    ], None


def discover_media(project: Path, inventory: dict[str, Any], external: list[str], out: Path) -> dict[str, Any]:
    candidates: list[Path] = [
        project / e["path"] for e in inventory["files"] if e["kind"] in {"image", "video"}
    ]
    warnings: list[str] = []
    for raw in external:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            warnings.append(f"External media path does not exist: {path.name}")
        elif path.is_dir():
            candidates.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)
        elif path.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            candidates.append(path)
    deduped: dict[str, Path] = {str(path.resolve()): path for path in candidates}
    items: list[dict[str, Any]] = []
    for path in sorted(deduped.values(), key=lambda p: str(p)):
        suffix = path.suffix.lower()
        reference = safe_reference(path, project)
        item: dict[str, Any] = {
            "id": f"MEDIA-{len(items) + 1:03d}",
            "type": "image" if suffix in IMAGE_EXTENSIONS else "video",
            "source": reference,
            "local_path": str(path.resolve()),
            "mime_type": mimetypes.guess_type(path.name)[0],
            "size": path.stat().st_size,
            "sensitive_name": is_sensitive_reference(reference),
        }
        if suffix in VIDEO_EXTENSIONS:
            metadata, warning = ffprobe(path)
            item["metadata"] = metadata
            frame_dir = out / "media" / "extracted_frames" / hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
            frames, frame_warning = extract_frames(path, frame_dir)
            for frame in frames:
                frame["path"] = Path(frame["path"]).relative_to(out).as_posix()
            item["frames"] = frames
            for value in (warning, frame_warning):
                if value:
                    warnings.append(value)
        items.append(item)
    return {"schema_version": SCHEMA_VERSION, "generated_at": now(), "items": items, "warnings": warnings}


def source(source_type: str, reference: str, **extra: Any) -> dict[str, Any]:
    return {"type": source_type, "reference": reference, **extra}


def claim(category: str, text: str, status: str, sources: list[dict[str, Any]], signals: list[str], *, public_safe: bool = False, notes: str | None = None) -> dict[str, Any]:
    return {
        "id": "",
        "category": category,
        "claim": text,
        "status": status,
        "sources": sources,
        "career_signals": signals,
        "notes": notes,
        "public_safe": public_safe,
        "sensitive": False,
        "supports": [],
        "contradicts": [],
        "origin": "baseline",
    }


def assign_ids(claims: list[dict[str, Any]], existing: Iterable[str] = ()) -> list[dict[str, Any]]:
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
        prefix = CATEGORY_PREFIX.get(str(item.get("category", "project")), "EVID")
        counters[prefix] += 1
        while f"{prefix}-{counters[prefix]:03d}" in used:
            counters[prefix] += 1
        item["id"] = f"{prefix}-{counters[prefix]:03d}"
        used.add(item["id"])
    return claims


def baseline_claims(profile: dict[str, Any], inventory: dict[str, Any], git: dict[str, Any], media: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for lang in profile["languages"]:
        claims.append(claim(
            "technology", f"The repository contains {lang['file_count']} {lang['name']} source or test files.",
            "CONFIRMED", [source("SOURCE_CODE", f"inventory:extension-count:{lang['name']}")],
            ["software_development"], public_safe=True,
        ))
    for project_type in profile["project_types"]:
        claims.append(claim(
            "project", f"Static discovery classifies the project provisionally as {project_type.replace('_', ' ')}.",
            "STRONG_INFERENCE", [source("INFERENCE", "project_profile.json")], ["product_engineering"],
            notes="Provisional classification; confirm through targeted artifact analysis.",
        ))
    files_by_kind: defaultdict[str, list[str]] = defaultdict(list)
    for entry in inventory["files"]:
        files_by_kind[entry["kind"]].append(entry["path"])
    kind_specs = {
        "test": ("testing", "Automated test artifacts exist in the repository.", "TEST", ["testing"]),
        "ci": ("delivery", "Continuous-integration configuration exists in the repository.", "CONFIG", ["ci_cd"]),
        "build_or_package": ("delivery", "Build or package metadata exists in the repository.", "BUILD_OR_PACKAGE_METADATA", ["deployment"]),
        "documentation": ("documentation", "Project documentation artifacts exist in the repository.", "DOCUMENTATION", ["documentation"]),
        "delivery": ("installation", "Installation or deployment-related artifacts exist in the repository.", "CONFIG", ["deployment"]),
    }
    for kind, (category, text, source_type, signals) in kind_specs.items():
        if files_by_kind[kind]:
            references = [source(source_type, path) for path in files_by_kind[kind][:20] if not is_sensitive_reference(path)]
            claims.append(claim(category, text, "CONFIRMED", references, signals, public_safe=True))
    if git.get("available"):
        count = git["commit_count_scanned"]
        first, latest = git.get("first_commit_date"), git.get("latest_commit_date")
        claims.append(claim(
            "git_history", f"Git history contains {count} inspected commits spanning {first or 'an unknown start date'} to {latest or 'an unknown end date'}.",
            "CONFIRMED", [source("GIT_HISTORY", "git log")], ["maintenance"], public_safe=False,
        ))
        contributor_count = len(git.get("contributors", []))
        if contributor_count:
            claims.append(claim(
                "ownership", f"Git history contains {contributor_count} distinct author identity records; this does not establish individual ownership boundaries.",
                "CONFIRMED", [source("GIT_HISTORY", "git log author metadata")], ["collaboration"],
                notes="Authorship is contextual evidence only and may include aliases or automation.",
            ))
    if media["items"]:
        images = sum(i["type"] == "image" for i in media["items"])
        videos = sum(i["type"] == "video" for i in media["items"])
        refs = [source("SCREENSHOT" if i["type"] == "image" else "VIDEO", i["source"]) for i in media["items"]]
        claims.append(claim("media", f"Available media includes {images} images and {videos} videos.", "CONFIRMED", refs, ["ui_engineering"]))
    return assign_ids(claims)


def default_questions(profile: dict[str, Any], observed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    multi = next((c for c in observed if c["category"] == "ownership"), None)
    questions = [
        ("ownership", "high", "Was this a solo or team project, and which parts did you personally own?", "Repository possession and Git authorship do not establish ownership."),
        ("problem", "high", "Why was this project created, and what concrete problem triggered it?", "The artifacts can show behavior but usually cannot prove the original motivation."),
        ("previous_workflow", "high", "What happened before this project existed?", "A previous manual or fragmented workflow may explain the project's professional value."),
        ("users", "high", "Who actually used this project, in what roles, and how often?", "Code cannot establish real users or adoption."),
        ("impact", "high", "What outcomes did the project produce, and were any improvements measured or estimated?", "Impact must come from user testimony or identified measurements."),
        ("decisions", "medium", "Which important technical choice or workaround needs context that is not visible in the repository?", "Rationale and external constraints are often absent from artifacts."),
        ("maintenance", "medium", "How long was the project used and maintained, and what eventually happened to it?", "Repository activity does not fully establish operational lifespan."),
    ]
    result = []
    for index, (topic, priority, text, rationale) in enumerate(questions, 1):
        tentative = None
        if topic == "ownership" and multi:
            tentative = multi["claim"]
        elif topic == "previous_workflow" and profile["capabilities"].get("automation"):
            tentative = "The repository suggests automation, so it may have replaced repetitive manual steps."
        result.append({
            "id": f"CTX-{index:03d}", "topic": topic, "priority": priority,
            "question": text, "rationale": rationale, "tentative_answer": tentative,
            "status": "open", "answer": None, "created_at": now(), "answered_at": None,
        })
    return result


def normalize_claim(item: dict[str, Any], kind: str) -> dict[str, Any]:
    normalized = {
        "id": str(item.get("id", "")).strip(),
        "category": str(item.get("category", "project")).strip().lower(),
        "claim": str(item.get("claim", "")).strip(),
        "status": str(item.get("status", "USER_CONFIRMED" if kind == "interview" else "CONFIRMED")).upper(),
        "sources": list(item.get("sources", [])),
        "career_signals": sorted(set(map(str, item.get("career_signals", [])))),
        "notes": item.get("notes"),
        "public_safe": bool(item.get("public_safe", False)),
        "sensitive": bool(item.get("sensitive", False)),
        "supports": list(item.get("supports", [])),
        "contradicts": list(item.get("contradicts", [])),
        "origin": str(item.get("origin", "agent")),
    }
    if kind == "interview" and not normalized["sources"]:
        source_type = "USER_ESTIMATE" if normalized["status"] == "USER_ESTIMATE" else "USER_ATTESTATION"
        question_id = item.get("interview_question_id")
        normalized["sources"] = [{"type": source_type, "interview_question_id": question_id, "reference": question_id or "interview"}]
    return normalized


def merge_sources(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in left + right:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def reconcile(observed: list[dict[str, Any]], interview: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(item) for item in observed]
    by_id = {item["id"]: item for item in result}
    for user_claim in interview:
        item = dict(user_claim)
        if item["id"] in by_id:
            target = by_id[item["id"]]
            target["sources"] = merge_sources(target.get("sources", []), item.get("sources", []))
            target["supports"] = sorted(set(target.get("supports", []) + item.get("supports", [])))
            target["contradicts"] = sorted(set(target.get("contradicts", []) + item.get("contradicts", [])))
            if target["claim"] != item["claim"]:
                target["status"] = "CONTRADICTED"
                target["notes"] = "Observed and interview claims sharing this ID materially differ."
            continue
        result.append(item)
        by_id[item["id"]] = item
    for user_claim in interview:
        for target_id in user_claim.get("supports", []):
            if target_id in by_id:
                by_id[target_id]["sources"] = merge_sources(by_id[target_id].get("sources", []), user_claim.get("sources", []))
        for target_id in user_claim.get("contradicts", []):
            if target_id in by_id:
                target = by_id[target_id]
                target["status"] = "CONTRADICTED"
                target["contradicts"] = sorted(set(target.get("contradicts", []) + [user_claim["id"]]))
                target["notes"] = f"Conflicts with interview claim {user_claim['id']}; clarification is required."
    return result


def unresolved_questions(interview_data: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contradicted = {item["category"] for item in evidence if item["status"] == "CONTRADICTED"}
    result = []
    for question in interview_data.get("questions", []):
        if question["status"] in {"answered", "skipped", "resolved_by_evidence"}:
            continue
        copy = dict(question)
        if copy["topic"] in contradicted:
            copy["priority"] = "high"
            copy["rationale"] = "Observed and user evidence conflict in this topic; clarification is required."
        result.append(copy)
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(result, key=lambda q: (order.get(q["priority"], 3), q["id"]))


def claim_resolves_topic(item: dict[str, Any], topic: str) -> bool:
    categories = {
        "problem": {"problem"},
        "previous_workflow": {"previous_workflow"},
        "users": {"users"},
        "impact": {"impact"},
        "decisions": {"decisions", "constraints"},
        "maintenance": {"maintenance"},
    }.get(topic, set())
    if item.get("category") not in categories:
        return False
    return item.get("status") in {"CONFIRMED", "USER_CONFIRMED"}


def analyze_gaps(interview_data: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Refresh evidence-resolved questions and synthesize conflict clarification."""
    questions = interview_data.setdefault("questions", [])
    for question in questions:
        if question["status"] != "open" or question["topic"] == "ownership":
            continue
        if any(claim_resolves_topic(item, question["topic"]) for item in evidence):
            question["status"] = "resolved_by_evidence"
    existing = {q["id"] for q in questions}
    for item in evidence:
        if item.get("status") != "CONTRADICTED":
            continue
        qid = f"CONFLICT-{item['id']}"
        if qid not in existing:
            questions.append({
                "id": qid,
                "topic": item["category"],
                "priority": "high",
                "question": f"Observed and user evidence conflict about this claim: “{item['claim']}” What explains the discrepancy?",
                "rationale": "Contradictory evidence must be clarified or explicitly preserved.",
                "tentative_answer": None,
                "status": "open",
                "answer": None,
                "created_at": now(),
                "answered_at": None,
            })
            existing.add(qid)
    status_weight = {
        "CONFIRMED": 100, "USER_CONFIRMED": 100, "USER_ESTIMATE": 75,
        "STRONG_INFERENCE": 65, "WEAK_INFERENCE": 30,
        "USER_CONFIRMATION_REQUIRED": 15, "CONTRADICTED": 10, "UNKNOWN": 0,
    }
    topics = ["problem", "users", "previous_workflow", "automation", "impact", "ownership", "decisions", "maintenance"]
    importance = {"ownership": 100, "problem": 95, "users": 90, "previous_workflow": 90, "impact": 95, "decisions": 70, "maintenance": 65, "automation": 80}
    category_map = {
        "problem": {"problem"}, "users": {"users"}, "previous_workflow": {"previous_workflow"},
        "automation": {"automation", "domain", "workflow"}, "impact": {"impact"},
        "ownership": {"ownership"}, "decisions": {"decisions", "constraints"},
        "maintenance": {"maintenance", "git_history"},
    }
    assessments = []
    for topic in topics:
        relevant = [i for i in evidence if i.get("category") in category_map[topic]]
        scores = [status_weight.get(i.get("status"), 0) for i in relevant]
        completeness = max(scores, default=0)
        if topic == "ownership" and relevant and all("does not establish" in i.get("claim", "").lower() for i in relevant):
            completeness = 10
        assessments.append({
            "topic": topic,
            "completeness_percent": completeness,
            "importance": importance[topic],
            "interview_priority_score": round(importance[topic] * (100 - completeness) / 100),
            "supporting_claim_ids": [i["id"] for i in relevant],
        })
    open_items = unresolved_questions(interview_data, evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "assessment": sorted(assessments, key=lambda item: item["interview_priority_score"], reverse=True),
        "open_question_ids": [q["id"] for q in open_items],
        "high_value_open_count": sum(q["priority"] == "high" for q in open_items),
    }


def build_project(profile: dict[str, Any], evidence: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: defaultdict[str, list[str]] = defaultdict(list)
    signals = Counter()
    for item in evidence:
        by_category[item["category"]].append(item["id"])
        signals.update(item.get("career_signals", []))
    extensions: dict[str, Any] = {}
    types = set(profile["project_types"])
    if "host_application_plugin" in types:
        extensions["cad_bim_or_host_plugin"] = {"evidence_claim_ids": by_category["domain"] + by_category["integration"] + by_category["interface"]}
    if types & {"web_application", "service_or_web_backend"}:
        extensions["web"] = {"evidence_claim_ids": by_category["architecture"] + by_category["integration"] + by_category["delivery"]}
    if "data_or_research_tool" in types:
        extensions["data_research"] = {"evidence_claim_ids": by_category["domain"] + by_category["workflow"]}
    if "unknown_software_project" in types:
        extensions["unknown_ecosystem"] = {"investigation_required": True}
    return {
        "project": {"types": profile["project_types"], "ecosystems": profile["ecosystems"], "evidence_claim_ids": by_category["project"] + by_category["product"]},
        "problem": {"evidence_claim_ids": by_category["problem"]},
        "users": by_category["users"],
        "workflows": by_category["workflow"] + by_category["previous_workflow"],
        "technology": {"languages": profile["languages"], "evidence_claim_ids": by_category["technology"]},
        "architecture": {"evidence_claim_ids": by_category["architecture"]},
        "automation": by_category["automation"] + by_category["domain"],
        "testing": {"evidence_claim_ids": by_category["testing"]},
        "delivery": {"evidence_claim_ids": by_category["delivery"] + by_category["installation"] + by_category["configuration"]},
        "maintenance": {"evidence_claim_ids": by_category["maintenance"] + by_category["git_history"]},
        "ownership": {"evidence_claim_ids": by_category["ownership"]},
        "impact": by_category["impact"],
        "decisions": by_category["decisions"] + by_category["constraints"],
        "career_signals": dict(signals.most_common()),
        "unknowns": [{"question_id": q["id"], "topic": q["topic"], "priority": q["priority"]} for q in questions],
        "extensions": extensions,
    }


def render_open_questions(path: Path, questions: list[dict[str, Any]]) -> None:
    lines = ["# Open Questions", "", "Only unresolved questions with potential evidence value are retained.", ""]
    for priority, heading in (("high", "High Value"), ("medium", "Medium Value"), ("low", "Low Value / Optional")):
        lines += [f"## {heading}", ""]
        selected = [q for q in questions if q["priority"] == priority]
        if selected:
            for q in selected:
                tentative = f" Tentative interpretation: {q['tentative_answer']}" if q.get("tentative_answer") else ""
                lines.append(f"- **{q['id']} — {q['topic']}**: {q['question']}{tentative}")
        else:
            lines.append("- None.")
        lines.append("")
    atomic_text(path, "\n".join(lines))


def render_dossier(path: Path, profile: dict[str, Any], evidence: list[dict[str, Any]], questions: list[dict[str, Any]]) -> None:
    by_category: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        by_category[item["category"]].append(item)
    status_counts = Counter(item["status"] for item in evidence)
    signals = Counter(signal for item in evidence for signal in item.get("career_signals", []))
    lines = ["# Repo-Portfolio Project Dossier", "", "> Evidence-rich source material; not résumé or portfolio copy.", ""]
    for title, categories in DOSSIER_SECTIONS:
        lines += [f"## {title}", ""]
        if title == "Project Overview":
            lines.append(f"Provisional types: {', '.join(profile['project_types'])}. Ecosystems: {', '.join(profile['ecosystems'])}.")
            items = [item for category in categories for item in by_category[category]]
        elif title == "Evidence Confidence Summary":
            lines.extend(f"- {status}: {count}" for status, count in sorted(status_counts.items()))
            items = []
        elif title == "Career Signals":
            lines.extend(f"- {signal}: {count} supporting claim(s)" for signal, count in signals.most_common())
            if not signals:
                lines.append("No career signals have been tagged yet.")
            items = []
        elif title == "Evidence Index":
            for item in evidence:
                refs = ", ".join(str(s.get("reference", s.get("interview_question_id", "unknown"))) for s in item.get("sources", []))
                lines.append(f"- **{item['id']}** [{item['status']}] — {refs or 'no source'}")
            items = []
        elif title == "Remaining Unknowns":
            lines.extend(f"- **{q['id']}** ({q['priority']}): {q['question']}" for q in questions)
            if not questions:
                lines.append("No prioritized unknowns remain.")
            items = []
        else:
            items = [item for category in categories for item in by_category[category]]
        for item in items:
            lines.append(f"- **{item['id']}** [{item['status']}]: {item['claim']}")
            if item.get("notes"):
                lines.append(f"  - Note: {item['notes']}")
        if not items and title not in {"Evidence Confidence Summary", "Career Signals", "Evidence Index", "Remaining Unknowns"}:
            lines.append("No defensible evidence captured yet.")
        lines.append("")
    atomic_text(path, "\n".join(lines))


def render_public(path: Path, evidence: list[dict[str, Any]]) -> None:
    safe = [
        item for item in evidence
        if item.get("public_safe") and not item.get("sensitive") and item["status"] in {"CONFIRMED", "USER_CONFIRMED"}
    ]
    lines = ["# Public-Safe Staging Summary", "", "This is sanitized evidence staging material, not final portfolio copy.", ""]
    if safe:
        lines.extend(f"- **{item['id']}**: {item['claim']}" for item in safe)
    else:
        lines.append("No claims have been explicitly approved as public-safe.")
    atomic_text(path, "\n".join(lines) + "\n")


def finalize_project(project: Path, out: Path) -> dict[str, Any]:
    profile = read_json(out / "project_profile.json", {})
    observed_data = read_json(out / "observed_evidence.json", {"claims": []})
    interview_data = read_json(out / "interview_evidence.json", {"questions": [], "claims": []})
    evidence = reconcile(observed_data.get("claims", []), interview_data.get("claims", []))
    gap_analysis = analyze_gaps(interview_data, evidence)
    questions = unresolved_questions(interview_data, evidence)
    evidence_data = {"schema_version": SCHEMA_VERSION, "generated_at": now(), "claims": evidence}
    atomic_json(out / "evidence.json", evidence_data)
    interview_data["updated_at"] = now()
    atomic_json(out / "interview_evidence.json", interview_data)
    atomic_json(out / "gap_analysis.json", gap_analysis)
    atomic_json(out / "project.json", build_project(profile, evidence, questions))
    render_open_questions(out / "open_questions.md", questions)
    render_dossier(out / "dossier.md", profile, evidence, questions)
    render_public(out / "public_safe_summary.md", evidence)
    session = read_json(out / "session.json", {})
    if session.get("mode") == "static":
        session["phase"] = "static_complete"
    elif not any(q["priority"] == "high" for q in questions) and not any(i["status"] == "CONTRADICTED" for i in evidence):
        session["phase"] = "complete"
    elif session.get("pending_question_id"):
        session["phase"] = "interviewing"
    else:
        session["phase"] = "interview_ready"
    session["updated_at"] = now()
    atomic_json(out / "session.json", session)
    return {"claims": len(evidence), "open_questions": len(questions), "phase": session["phase"]}


def analyze(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}", file=sys.stderr)
        return 2
    out = output_dir(project, args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "media" / "extracted_frames").mkdir(parents=True, exist_ok=True)
    prior_session = read_json(out / "session.json", {})
    prior_interview = read_json(out / "interview_evidence.json", None)
    prior_observed = read_json(out / "observed_evidence.json", None)
    inventory = inventory_project(project, args.deep)
    profile = discover_profile(project, inventory)
    plan = make_plan(profile, args.deep)
    git = git_summary(project)
    media = discover_media(project, inventory, args.media or [], out)
    observed = baseline_claims(profile, inventory, git, media)
    compatible = prior_session.get("project_root") == str(project) and prior_interview
    if compatible and prior_observed:
        baseline_ids = {item["id"] for item in observed}
        preserved = [
            item for item in prior_observed.get("claims", [])
            if item.get("origin") != "baseline" and item.get("id") not in baseline_ids
        ]
        assign_ids(preserved, baseline_ids)
        observed.extend(preserved)
    interview = prior_interview if compatible else {
        "schema_version": SCHEMA_VERSION, "updated_at": now(),
        "questions": default_questions(profile, observed), "claims": [],
    }
    session = {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(project),
        "output_directory": str(out),
        "project_fingerprint": inventory["fingerprint"],
        "mode": "static" if args.static else ("deep" if args.deep else "default"),
        "phase": "artifact_analysis",
        "pending_question_id": prior_session.get("pending_question_id") if compatible else None,
        "created_at": prior_session.get("created_at", now()) if compatible else now(),
        "updated_at": now(),
        "warnings": inventory["warnings"] + git.get("warnings", []) + media["warnings"],
    }
    atomic_json(out / "session.json", session)
    atomic_json(out / "inventory.json", inventory)
    atomic_json(out / "project_profile.json", profile)
    atomic_json(out / "analysis_plan.json", plan)
    atomic_json(out / "git_history.json", git)
    atomic_json(out / "media" / "media_index.json", media)
    atomic_json(out / "observed_evidence.json", {"schema_version": SCHEMA_VERSION, "generated_at": now(), "claims": observed})
    atomic_json(out / "interview_evidence.json", interview)
    result = finalize_project(project, out)
    print(json.dumps({"output": str(out), **result}, indent=2))
    return 0


def payload_claims(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "claims" in payload:
        return payload["claims"]
    if isinstance(payload, dict) and "claim" in payload:
        return [payload]
    return []


def ingest(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    payload = read_json(Path(args.input).expanduser().resolve(), None)
    if payload is None:
        print("Input payload is not valid JSON.", file=sys.stderr)
        return 2
    target = out / ("observed_evidence.json" if args.kind == "observed" else "interview_evidence.json")
    data = read_json(target, {"schema_version": SCHEMA_VERSION, "claims": [], "questions": []})
    existing_ids = [item["id"] for item in data.get("claims", [])]
    incoming = [normalize_claim(item, args.kind) for item in payload_claims(payload)]
    assign_ids(incoming, existing_ids)
    data.setdefault("claims", []).extend(incoming)
    if args.kind == "interview" and isinstance(payload, dict):
        question_update = payload.get("question")
        if question_update:
            qid = question_update.get("id") or question_update.get("question_id")
            for question in data.setdefault("questions", []):
                if question["id"] == qid:
                    question["answer"] = question_update.get("answer")
                    question["status"] = question_update.get("status", "answered")
                    question["answered_at"] = now()
                    break
            session = read_json(out / "session.json", {})
            if session.get("pending_question_id") == qid:
                session["pending_question_id"] = None
                session["updated_at"] = now()
                atomic_json(out / "session.json", session)
        for extra in payload.get("follow_up_questions", []):
            questions = data.setdefault("questions", [])
            ids = {q["id"] for q in questions}
            if not extra.get("id"):
                numbers = [int(m.group(1)) for q in questions if (m := re.fullmatch(r"CTX-(\d+)", q["id"]))]
                extra["id"] = f"CTX-{max(numbers, default=0) + 1:03d}"
            if extra["id"] not in ids:
                extra = {"priority": "medium", "tentative_answer": None, "status": "open", "answer": None, "created_at": now(), "answered_at": None, **extra}
                questions.append(extra)
    data["updated_at"] = now()
    atomic_json(target, data)
    result = finalize_project(project, out)
    print(json.dumps({"ingested": len(incoming), **result}, indent=2))
    return 0


def next_question(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    session = read_json(out / "session.json", {})
    interview = read_json(out / "interview_evidence.json", {})
    if session.get("mode") == "static":
        print(json.dumps({"question": None, "reason": "Static mode does not conduct interviews."}, indent=2))
        return 0
    pending = session.get("pending_question_id")
    if pending:
        question = next((q for q in interview.get("questions", []) if q["id"] == pending), None)
        print(json.dumps({"question": question, "resumed": True}, indent=2))
        return 0
    evidence = read_json(out / "evidence.json", {"claims": []})["claims"]
    questions = unresolved_questions(interview, evidence)
    if not questions:
        print(json.dumps({"question": None, "reason": "No valuable unresolved questions remain."}, indent=2))
        return 0
    question = questions[0]
    for stored in interview["questions"]:
        if stored["id"] == question["id"]:
            stored["status"] = "pending"
            break
    interview["updated_at"] = now()
    session["pending_question_id"] = question["id"]
    session["phase"] = "interviewing"
    session["updated_at"] = now()
    atomic_json(out / "interview_evidence.json", interview)
    atomic_json(out / "session.json", session)
    print(json.dumps({"question": question, "resumed": False}, indent=2))
    return 0


def validation_errors(out: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_OUTPUTS:
        if not (out / relative).exists():
            errors.append(f"Missing required artifact: {relative}")
    parsed: dict[str, Any] = {}
    for name in ("project.json", "observed_evidence.json", "interview_evidence.json", "evidence.json", "session.json", "project_profile.json", "analysis_plan.json", "media/media_index.json"):
        if not (out / name).exists():
            continue
        value = read_json(out / name, None)
        if value is None:
            errors.append(f"Malformed JSON: {name}")
        else:
            parsed[name] = value
    project_data = parsed.get("project.json", {})
    missing_core = [key for key in CORE_KEYS if key not in project_data]
    if missing_core:
        errors.append(f"project.json is missing universal core keys: {', '.join(missing_core)}")
    all_claims = parsed.get("evidence.json", {}).get("claims", [])
    ids = [item.get("id") for item in all_claims]
    duplicates = sorted({value for value in ids if value and ids.count(value) > 1})
    if duplicates:
        errors.append(f"Duplicate evidence IDs: {', '.join(duplicates)}")
    id_set = set(ids)
    for item in all_claims:
        cid = item.get("id", "<missing>")
        if not re.fullmatch(r"[A-Z]+-\d{3,}", str(cid)):
            errors.append(f"Invalid evidence ID: {cid}")
        if item.get("status") not in STATUSES:
            errors.append(f"{cid} uses invalid status {item.get('status')}")
        sources = item.get("sources", [])
        if item.get("status") not in {"UNKNOWN", "USER_CONFIRMATION_REQUIRED"} and not sources:
            errors.append(f"{cid} has no provenance")
        invalid_sources = [s.get("type") for s in sources if s.get("type") not in SOURCE_TYPES]
        if invalid_sources:
            errors.append(f"{cid} uses invalid source types: {invalid_sources}")
        if item.get("status") == "USER_ESTIMATE" and any(s.get("type") != "USER_ESTIMATE" for s in sources):
            errors.append(f"{cid} is a user estimate without exclusively USER_ESTIMATE provenance")
        if item.get("category") == "ownership" and item.get("status") in {"CONFIRMED", "USER_CONFIRMED"}:
            source_types = {s.get("type") for s in sources}
            text = item.get("claim", "").lower()
            if any(word in text for word in ("owned", "built", "designed", "responsible")) and not source_types & {"USER_ATTESTATION", "DOCUMENTATION"}:
                errors.append(f"{cid} makes a personal ownership claim without suitable support")
        static_types = {s.get("type") for s in sources} <= ARTIFACT_SOURCES
        if static_types and re.search(r"\b(tests? pass(?:ed|ing)?|installer works?|application (?:runs?|launches?)|deployment succeeds?)\b", item.get("claim", ""), re.I):
            errors.append(f"{cid} asserts runtime behavior from static evidence")
        if item.get("status") == "CONTRADICTED" and not item.get("contradicts"):
            errors.append(f"{cid} is contradicted but has no contradiction relationship")
        for relation in item.get("supports", []) + item.get("contradicts", []):
            if relation not in id_set:
                errors.append(f"{cid} references unknown related claim {relation}")
    dossier = (out / "dossier.md").read_text(encoding="utf-8") if (out / "dossier.md").exists() else ""
    for cid in id_set:
        if cid and cid not in dossier:
            errors.append(f"Dossier evidence index omits {cid}")
    public = (out / "public_safe_summary.md").read_text(encoding="utf-8") if (out / "public_safe_summary.md").exists() else ""
    public_ids = set(re.findall(r"\*\*([A-Z]+-\d+)\*\*", public))
    by_id = {item["id"]: item for item in all_claims if item.get("id")}
    for cid in public_ids:
        item = by_id.get(cid)
        if not item or not item.get("public_safe") or item.get("sensitive") or item.get("status") not in {"CONFIRMED", "USER_CONFIRMED"}:
            errors.append(f"Public summary contains unsafe or unsupported claim {cid}")
    questions_text = (out / "open_questions.md").read_text(encoding="utf-8") if (out / "open_questions.md").exists() else ""
    for heading in ("## High Value", "## Medium Value", "## Low Value / Optional"):
        if heading not in questions_text:
            errors.append(f"open_questions.md is missing heading: {heading}")
    return errors


def validate(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    errors = validation_errors(out)
    result = {"valid": not errors, "errors": errors, "validated_at": now()}
    atomic_json(out / "validation.json", result)
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


def finalize_command(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    out = output_dir(project, args.output)
    if not (out / "session.json").exists():
        print("No Repo-Portfolio session exists. Run analyze first.", file=sys.stderr)
        return 2
    print(json.dumps(finalize_project(project, out), indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Static evidence pipeline for the Repo-Portfolio Codex skill.")
    root.add_argument("--version", action="version", version=f"Repo-Portfolio {SCHEMA_VERSION}")
    commands = root.add_subparsers(dest="command", required=True)
    analyze_parser = commands.add_parser("analyze", help="Discover and statically analyze a project.")
    analyze_parser.add_argument("project")
    analyze_parser.add_argument("--output")
    analyze_parser.add_argument("--media", action="append", default=[])
    analyze_parser.add_argument("--deep", action="store_true")
    analyze_parser.add_argument("--static", action="store_true")
    analyze_parser.set_defaults(handler=analyze)
    for name, handler in (("finalize", finalize_command), ("next-question", next_question), ("validate", validate)):
        command = commands.add_parser(name)
        command.add_argument("project")
        command.add_argument("--output")
        command.set_defaults(handler=handler)
    ingest_parser = commands.add_parser("ingest", help="Ingest normalized observed or interview claims.")
    ingest_parser.add_argument("project")
    ingest_parser.add_argument("--output")
    ingest_parser.add_argument("--kind", choices=("observed", "interview"), required=True)
    ingest_parser.add_argument("--input", required=True)
    ingest_parser.set_defaults(handler=ingest)
    return root


def main() -> int:
    if sys.version_info < (3, 12):
        print("Repo-Portfolio requires Python 3.12 or newer.", file=sys.stderr)
        return 2
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
