#!/usr/bin/env python3
"""Safe, explicit-input media retrieval and preprocessing for Repo-Portfolio."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


IMAGE_LIMIT = 25 * 1024 * 1024
VIDEO_LIMIT = 500 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be",
}
MIME_EXTENSIONS = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp", "image/tiff": ".tiff",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
    "video/x-msvideo": ".avi", "video/x-matroska": ".mkv",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_process(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            check=False, env={**os.environ, "LC_ALL": "C"},
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def is_url(value: str) -> bool:
    return urllib.parse.urlsplit(value).scheme.lower() in {"http", "https"}


def is_youtube_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and (parsed.hostname or "").lower() in YOUTUBE_HOSTS


def safe_reference(path: Path, project: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        parent_hash = hashlib.sha256(str(path.resolve().parent).encode()).hexdigest()[:8]
        return f"external:{parent_hash}/{path.name}"


def cache_relative(path: Path, out: Path) -> str:
    return path.resolve().relative_to(out.resolve()).as_posix()


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def ffprobe_media(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    executable = shutil.which("ffprobe")
    if not executable:
        return None, "ffprobe is unavailable; video metadata could not be verified."
    code, stdout, stderr = run_process([
        executable, "-v", "error", "-show_entries",
        "format=duration,format_name:stream=codec_name,width,height,duration",
        "-of", "json", str(path),
    ], path.parent, 45)
    if code:
        return None, f"ffprobe failed for {path.name}: {stderr or 'unknown error'}"
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError:
        return None, f"ffprobe returned malformed metadata for {path.name}."


def duration_from_metadata(metadata: dict[str, Any] | None) -> float | None:
    if not metadata:
        return None
    candidates = [metadata.get("duration"), metadata.get("format", {}).get("duration")]
    candidates.extend(stream.get("duration") for stream in metadata.get("streams", []))
    for value in candidates:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def extract_frames(path: Path, destination: Path, out: Path, source: str) -> tuple[list[dict[str, Any]], list[str]]:
    executable = shutil.which("ffmpeg")
    if not executable:
        return [], ["ffmpeg is unavailable; representative frames were not extracted."]
    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.glob("*.png"):
        existing.unlink()

    def attempt(prefix: str, filter_value: str, method: str) -> tuple[list[dict[str, Any]], str | None]:
        pattern = destination / f"{prefix}-%03d.png"
        code, _, stderr = run_process([
            executable, "-y", "-hide_banner", "-loglevel", "info", "-i", str(path),
            "-vf", filter_value, "-fps_mode", "vfr", "-frames:v", "12", str(pattern),
        ], path.parent, 120)
        files = sorted(destination.glob(f"{prefix}-*.png"))
        pts = [float(value) for value in re.findall(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)", stderr)]
        frames = []
        for index, frame in enumerate(files):
            seconds = pts[index] if index < len(pts) else (index * 30.0 if method == "periodic" else None)
            frames.append({
                "path": cache_relative(frame, out),
                "sequence": index + 1,
                "source": source,
                "timestamp_seconds": seconds,
                "timestamp": format_timestamp(seconds) if seconds is not None else None,
                "timestamp_method": "decoded_pts" if index < len(pts) else "periodic_estimate",
            })
        if code and not frames:
            return [], stderr or "unknown ffmpeg error"
        return frames, None

    frames, error = attempt(
        "scene", "select=gt(scene\\,0.35),showinfo,scale=min(1600\\,iw):-2", "scene"
    )
    if not frames or any(frame["timestamp_seconds"] is None for frame in frames):
        for existing in destination.glob("scene-*.png"):
            existing.unlink()
        frames, fallback_error = attempt(
            "periodic",
            "select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,30),showinfo,scale=min(1600\\,iw):-2",
            "periodic",
        )
        error = fallback_error or error
    warnings = [f"ffmpeg failed for {path.name}: {error}"] if error and not frames else []
    return frames, warnings


def image_signature(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def video_signature(data: bytes) -> str | None:
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1aE\xdf\xa3"):
        lowered = data.lower()
        return "video/x-matroska" if b"matroska" in lowered else "video/webm"
    if data.startswith(b"RIFF") and data[8:12] == b"AVI ":
        return "video/x-msvideo"
    return None


class LimitedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, maximum: int = 5) -> None:
        super().__init__()
        self.maximum = maximum
        self.count = 0

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        self.count += 1
        if self.count > self.maximum:
            raise urllib.error.HTTPError(req.full_url, code, "Too many redirects", headers, fp)
        if urllib.parse.urlsplit(newurl).scheme.lower() not in {"http", "https"}:
            raise urllib.error.HTTPError(req.full_url, code, "Unsafe redirect scheme", headers, fp)
        validate_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_public_host(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only explicit HTTP/HTTPS media URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not supported.")
    try:
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or default_port)}
    except socket.gaierror as exc:
        raise ValueError(f"Media host could not be resolved: {exc}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if os.environ.get("REPO_PORTFOLIO_ALLOW_PRIVATE_MEDIA") == "1":
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError("Remote media URLs must resolve to public network addresses.")


def classify_content(content_type: str, url: str) -> tuple[str, int, str]:
    mime = content_type.split(";", 1)[0].strip().lower()
    extension = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if mime.startswith("image/") or (mime in {"", "application/octet-stream"} and extension in IMAGE_EXTENSIONS):
        return "image", IMAGE_LIMIT, MIME_EXTENSIONS.get(mime, extension or ".img")
    if mime.startswith("video/") or (mime in {"", "application/octet-stream"} and extension in VIDEO_EXTENSIONS):
        return "video", VIDEO_LIMIT, MIME_EXTENSIONS.get(mime, extension or ".video")
    if mime in {"text/html", "application/xhtml+xml"}:
        raise ValueError("The supplied URL returned HTML; Repo-Portfolio does not crawl pages.")
    raise ValueError(f"Unsupported remote media content type: {mime or 'unknown'}")


def retrieve_direct(url: str, cache: Path) -> dict[str, Any]:
    validate_public_host(url)
    cache.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(LimitedRedirectHandler())
    request = urllib.request.Request(url, headers={"User-Agent": "Repo-Portfolio/1.1", "Accept": "image/*,video/*"})
    started = utc_now()
    try:
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            validate_public_host(final_url)
            media_type, limit, extension = classify_content(response.headers.get("Content-Type", ""), final_url)
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > limit:
                raise ValueError(f"Remote {media_type} exceeds the {limit // (1024 * 1024)} MiB limit.")
            target = cache / f"media{extension}"
            fd, temporary = tempfile.mkstemp(prefix=".download-", dir=cache)
            total = 0
            prefix = b""
            try:
                with os.fdopen(fd, "wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > limit:
                            raise ValueError(f"Remote {media_type} exceeds the {limit // (1024 * 1024)} MiB limit.")
                        if len(prefix) < 4096:
                            prefix += chunk[:4096 - len(prefix)]
                        handle.write(chunk)
                if declared and total != int(declared):
                    raise ValueError("Remote media response was truncated.")
                detected = image_signature(prefix) if media_type == "image" else video_signature(prefix)
                if not detected:
                    raise ValueError(f"Downloaded content does not have a recognized {media_type} signature.")
                declared_mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                aliases = {
                    ("image/jpg", "image/jpeg"), ("video/quicktime", "video/mp4"),
                    ("video/x-m4v", "video/mp4"),
                }
                if declared_mime not in {"", "application/octet-stream", detected} and (declared_mime, detected) not in aliases:
                    raise ValueError(f"Declared MIME {declared_mime} does not match downloaded {detected} content.")
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return {"ok": False, "warning": f"Remote media retrieval failed: {exc}", "original_url": url, "retrieved_at": started}
    return {
        "ok": True, "original_url": url, "resolved_url": final_url,
        "retrieved_at": started, "media_type": media_type, "mime_type": detected,
        "size": total, "path": target,
    }


def choose_caption(metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    subtitles = metadata.get("subtitles") or {}
    automatic = metadata.get("automatic_captions") or {}
    for kind, options in (("human", subtitles), ("automatic", automatic)):
        if not options:
            continue
        languages = sorted(options)
        language = next((value for value in languages if value == "en" or value.startswith("en-")), languages[0])
        return language, kind
    return None, None


def subtitle_to_cues(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(
        r"(?m)^(\d{2}:)?(\d{2}):(\d{2})[\.,](\d{3})\s+-->\s+[^\n]+\n((?:(?!\n\s*\n).)+)", re.S
    )
    cues = []
    for match in pattern.finditer(text):
        hours = int(match.group(1)[:-1]) if match.group(1) else 0
        seconds = hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 1000
        body = re.sub(r"<[^>]+>", "", match.group(5)).replace("\n", " ").strip()
        if body:
            cues.append({"timestamp_seconds": seconds, "timestamp": format_timestamp(seconds), "text": body})
    return cues


def retrieve_youtube(url: str, cache: Path) -> dict[str, Any]:
    executable = shutil.which("yt-dlp")
    retrieved_at = utc_now()
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        return {
            "ok": False, "original_url": url, "retrieved_at": retrieved_at,
            "warning": "YouTube URLs containing embedded credentials are not supported.",
        }
    if not executable:
        return {"ok": False, "original_url": url, "retrieved_at": retrieved_at, "warning": "yt-dlp is unavailable; YouTube media was not retrieved."}
    cache.mkdir(parents=True, exist_ok=True)
    base = [executable, "--no-config", "--no-playlist", "--socket-timeout", "30", "--retries", "2"]
    code, stdout, stderr = run_process(base + ["--dump-single-json", "--skip-download", url], cache, 90)
    if code:
        return {"ok": False, "original_url": url, "retrieved_at": retrieved_at, "warning": f"YouTube metadata retrieval failed: {stderr or 'unavailable video'}"}
    try:
        metadata = json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": False, "original_url": url, "retrieved_at": retrieved_at, "warning": "yt-dlp returned malformed metadata."}
    language, caption_kind = choose_caption(metadata)
    command = base + [
        "--max-filesize", str(VIDEO_LIMIT), "--paths", str(cache),
        "--output", "media.%(ext)s", "--format", "bestvideo[height<=720]/best[height<=720]/worst",
        "--write-info-json",
    ]
    if language:
        command += ["--write-subs", "--write-auto-subs", "--sub-langs", language]
    command.append(url)
    code, _, download_error = run_process(command, cache, 300)
    media_files = [p for p in cache.glob("media.*") if p.suffix.lower() in VIDEO_EXTENSIONS]
    if code or not media_files:
        return {
            "ok": False, "original_url": url, "retrieved_at": retrieved_at,
            "title": metadata.get("title"), "duration": metadata.get("duration"),
            "warning": f"YouTube video retrieval failed: {download_error or 'no suitable video stream'}",
        }
    media_path = sorted(media_files)[0]
    if media_path.stat().st_size > VIDEO_LIMIT:
        media_path.unlink()
        return {"ok": False, "original_url": url, "retrieved_at": retrieved_at, "warning": "YouTube video exceeded the 500 MiB limit."}
    try:
        with media_path.open("rb") as handle:
            detected_mime = video_signature(handle.read(4096))
    except OSError as exc:
        return {
            "ok": False, "original_url": url, "retrieved_at": retrieved_at,
            "warning": f"YouTube cached video could not be validated: {exc}",
        }
    if not detected_mime:
        media_path.unlink()
        return {
            "ok": False, "original_url": url, "retrieved_at": retrieved_at,
            "warning": "YouTube retrieval did not produce a recognized video container.",
        }
    subtitle_files = sorted(p for p in cache.glob("media.*") if p.suffix.lower() in {".vtt", ".srt"})
    cues = subtitle_to_cues(subtitle_files[0]) if subtitle_files else []
    transcript_path = None
    if cues:
        transcript_path = cache / "transcript.json"
        transcript_path.write_text(json.dumps({"language": language, "kind": caption_kind, "cues": cues}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "ok": True, "original_url": url, "resolved_url": metadata.get("webpage_url") or url,
        "retrieved_at": retrieved_at, "media_type": "video", "mime_type": detected_mime,
        "size": media_path.stat().st_size, "path": media_path, "title": metadata.get("title"),
        "duration": metadata.get("duration"), "caption_language": language,
        "caption_kind": caption_kind, "caption_path": subtitle_files[0] if subtitle_files else None,
        "transcript_path": transcript_path,
    }


def local_candidates(project: Path, inventory_files: list[dict[str, Any]], inputs: Iterable[str]) -> tuple[list[Path], list[str]]:
    candidates = [project / item["path"] for item in inventory_files if item.get("kind") in {"image", "video"}]
    warnings = []
    for raw in inputs:
        if is_url(raw):
            continue
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            warnings.append(f"Local media path does not exist: {path.name}")
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                root_path = Path(root)
                dirs[:] = sorted(
                    name for name in dirs
                    if name not in {".git", ".repo-portfolio", "node_modules", "vendor"}
                    and not (root_path / name).is_symlink()
                )
                candidates.extend(
                    root_path / name for name in sorted(files)
                    if not (root_path / name).is_symlink()
                    and (root_path / name).suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
                )
        elif path.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            candidates.append(path)
        else:
            warnings.append(f"Unsupported local media type: {path.name}")
    unique = {str(path.resolve()): path for path in candidates if path.exists() and not path.is_symlink()}
    return sorted(unique.values(), key=lambda value: str(value)), warnings


def collect_media(project: Path, inventory_files: list[dict[str, Any]], inputs: list[str], out: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    candidates, warnings = local_candidates(project, inventory_files, inputs)
    sources: list[tuple[str, Path, dict[str, Any]]] = []
    for path in candidates:
        media_type = "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "video"
        sources.append((safe_reference(path, project), path, {"media_type": media_type, "retrieved_at": None}))
    for value in inputs:
        if not is_url(value):
            continue
        cache = out / "media" / "cache" / hashlib.sha256(value.encode()).hexdigest()[:16]
        result = retrieve_youtube(value, cache) if is_youtube_url(value) else retrieve_direct(value, cache)
        if not result.get("ok"):
            warnings.append(result.get("warning", f"Remote media unavailable: {value}"))
            items.append({
                "id": f"MEDIA-{len(items) + 1:03d}", "type": "unavailable",
                "source": value, "original_url": value, "retrieved_at": result.get("retrieved_at"),
                "warnings": [result.get("warning")],
            })
            continue
        sources.append((value, result["path"], result))
    for canonical, path, metadata in sources:
        media_type = metadata["media_type"]
        item: dict[str, Any] = {
            "id": f"MEDIA-{len(items) + 1:03d}", "type": media_type,
            "source": canonical, "original_url": metadata.get("original_url"),
            "resolved_url": metadata.get("resolved_url"), "retrieved_at": metadata.get("retrieved_at"),
            "title": metadata.get("title"), "mime_type": metadata.get("mime_type") or mimetypes.guess_type(path.name)[0],
            "size": path.stat().st_size, "cached_path": cache_relative(path, out) if metadata.get("original_url") else None,
            "local_path": str(path.resolve()), "duration": metadata.get("duration"), "warnings": [],
        }
        if media_type == "video":
            probe, warning = ffprobe_media(path)
            item["probe"] = probe
            item["duration"] = item["duration"] or duration_from_metadata(probe)
            frames, frame_warnings = extract_frames(
                path, out / "media" / "extracted_frames" / hashlib.sha256(canonical.encode()).hexdigest()[:12], out, canonical
            )
            item["frames"] = frames
            item["caption_language"] = metadata.get("caption_language")
            item["caption_kind"] = metadata.get("caption_kind")
            item["caption_path"] = cache_relative(metadata["caption_path"], out) if metadata.get("caption_path") else None
            item["transcript_path"] = cache_relative(metadata["transcript_path"], out) if metadata.get("transcript_path") else None
            if warning:
                item["warnings"].append(warning)
            item["warnings"].extend(frame_warnings)
        items.append(item)
    return {"schema_version": "1.1", "generated_at": utc_now(), "items": items, "warnings": warnings}
