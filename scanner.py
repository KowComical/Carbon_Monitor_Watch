from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MIRROR_MARKER_PATH = ROOT / "log_mirror" / ".last_sync"
LOG_SUFFIXES = {".log", ".out", ".txt"}
SCAN_LIMIT_BYTES = 2_500_000
CACHE_TTL_SECONDS = 3600

DATE_RE = re.compile(r"(20\d{2})[-/_.](\d{2})[-/_.](\d{2})")
OK_RE = re.compile(r"\b(finished|completed|success|succeeded|updated|done)\b", re.I)
WARN_RE = re.compile(r"\b(warn|warning|timeout|retry|deprecated)\b", re.I)

_CACHE: dict[str, Any] = {"built_at": 0.0, "mirror_version": None, "data": None}
_CACHE_LOCK = threading.Lock()


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def mirror_version() -> float | None:
    try:
        return MIRROR_MARKER_PATH.stat().st_mtime
    except OSError:
        return None


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def parse_date(text: str, fallback_mtime: float) -> str:
    match = DATE_RE.search(text)
    if match:
        return "-".join(match.groups())
    return datetime.fromtimestamp(fallback_mtime).strftime("%Y-%m-%d")


def is_hidden_or_temp(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def iter_log_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if is_hidden_or_temp(rel):
            continue
        if path.suffix.lower() not in LOG_SUFFIXES:
            continue
        files.append(path)
    return files


def read_for_scan(path: Path) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > SCAN_LIMIT_BYTES:
                fh.seek(max(0, size - SCAN_LIMIT_BYTES))
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def looks_like_zero_count(line: str, word: str) -> bool:
    lower = line.lower()
    return (
        f"{word}=0" in lower
        or f"{word}: 0" in lower
        or f"{word}s=0" in lower
        or f"{word}s: 0" in lower
        or f"0 {word}" in lower
        or f"0 {word}s" in lower
    )


def is_error_line(line: str) -> bool:
    lower = line.lower()
    if "traceback" in lower or "exception" in lower or "critical" in lower or "fatal" in lower:
        return True
    if "server error" in lower or "http error" in lower:
        return True
    if "error" in lower and not looks_like_zero_count(lower, "error"):
        return True
    if ("failed" in lower or "failure" in lower) and not looks_like_zero_count(lower, "failed"):
        return True
    return False


def is_warning_line(line: str) -> bool:
    lower = line.lower()
    if looks_like_zero_count(lower, "warning") or looks_like_zero_count(lower, "warn"):
        return False
    return bool(WARN_RE.search(line))


def last_meaningful_line(lines: list[str]) -> str:
    for line in reversed(lines):
        clean = line.strip()
        if clean:
            return clean[-420:]
    return ""


def scan_log(path: Path, rel: str) -> dict[str, Any]:
    stat = path.stat()
    text = read_for_scan(path)
    lines = text.splitlines()
    error_lines: list[str] = []
    warning_lines: list[str] = []
    error_count = 0
    warning_count = 0
    ok_count = 0

    for line in lines:
        if is_error_line(line):
            error_count += 1
            if len(error_lines) < 8:
                error_lines.append(line.strip()[:500])
        elif is_warning_line(line):
            warning_count += 1
            if len(warning_lines) < 8:
                warning_lines.append(line.strip()[:500])
        if OK_RE.search(line):
            ok_count += 1

    if error_count:
        status = "error"
    elif warning_count:
        status = "warning"
    elif ok_count:
        status = "ok"
    else:
        status = "unknown"

    log_date = parse_date(rel, stat.st_mtime)
    return {
        "path": rel,
        "name": Path(rel).name,
        "date": log_date,
        "status": status,
        "size": stat.st_size,
        "sizeLabel": human_bytes(stat.st_size),
        "mtime": stat.st_mtime,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "errors": error_count,
        "warnings": warning_count,
        "okSignals": ok_count,
        "lastLine": last_meaningful_line(lines),
        "highlights": error_lines + warning_lines,
    }


def severity(status: str) -> int:
    return {
        "error": 5,
        "stale": 4,
        "warning": 3,
        "unknown": 2,
        "ok": 1,
        "empty": 0,
    }.get(status, 0)


def aggregate_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "empty"
    return max((item["status"] for item in items), key=severity)


def build_project(project_cfg: dict[str, Any]) -> dict[str, Any]:
    mirror = (ROOT / project_cfg["mirror"]).resolve()
    logs = []
    for path in iter_log_files(mirror):
        rel = path.relative_to(mirror).as_posix()
        try:
            logs.append(scan_log(path, rel))
        except OSError:
            continue

    logs.sort(key=lambda item: (item["date"], item["mtime"], item["path"]), reverse=True)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in logs:
        grouped.setdefault(item["date"], []).append(item)

    dates = []
    for day, items in grouped.items():
        latest_mtime = max(item["mtime"] for item in items)
        dates.append(
            {
                "date": day,
                "count": len(items),
                "status": aggregate_status(items),
                "errors": sum(item["errors"] for item in items),
                "warnings": sum(item["warnings"] for item in items),
                "latestModified": datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "mtime": latest_mtime,
            }
        )
    dates.sort(key=lambda item: item["date"], reverse=True)

    latest_date = dates[0]["date"] if dates else None
    latest_items = grouped.get(latest_date, []) if latest_date else []
    project_status = aggregate_status(latest_items)
    if latest_date and project_status not in {"error", "empty"}:
        try:
            days_old = (date.today() - datetime.strptime(latest_date, "%Y-%m-%d").date()).days
        except ValueError:
            days_old = 0
        if days_old > 2:
            project_status = "stale"
    else:
        days_old = None

    latest_log = latest_items[0] if latest_items else None
    total_size = sum(item["size"] for item in logs)

    return {
        "id": project_cfg["id"],
        "name": project_cfg["name"],
        "server": project_cfg["server"],
        "source": project_cfg["source"],
        "mirror": project_cfg["mirror"],
        "status": project_status,
        "latestDate": latest_date,
        "daysOld": days_old,
        "latestFile": latest_log["path"] if latest_log else None,
        "latestLine": latest_log["lastLine"] if latest_log else "",
        "fileCount": len(logs),
        "dateCount": len(dates),
        "totalBytes": total_size,
        "totalSize": human_bytes(total_size),
        "latestErrors": sum(item["errors"] for item in latest_items),
        "latestWarnings": sum(item["warnings"] for item in latest_items),
        "dates": dates,
        "logsByDate": grouped,
    }


def build_index() -> dict[str, Any]:
    config = load_config()
    projects = [build_project(project) for project in config["projects"]]
    projects.sort(key=lambda item: (severity(item["status"]), item["latestDate"] or ""), reverse=True)
    latest_dates = [project["latestDate"] for project in projects if project["latestDate"]]
    return {
        "appName": config.get("app_name", "Carbon Monitor Watch"),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "projectCount": len(projects),
        "fileCount": sum(project["fileCount"] for project in projects),
        "dateCount": sum(project["dateCount"] for project in projects),
        "totalBytes": sum(project["totalBytes"] for project in projects),
        "totalSize": human_bytes(sum(project["totalBytes"] for project in projects)),
        "latestDate": max(latest_dates) if latest_dates else None,
        "projects": projects,
    }


def get_index(force: bool = False) -> dict[str, Any]:
    now = time.time()
    version = mirror_version()
    cache_is_fresh = (
        _CACHE["data"] is not None
        and _CACHE["mirror_version"] == version
        and now - _CACHE["built_at"] < CACHE_TTL_SECONDS
    )
    if not force and cache_is_fresh:
        return _CACHE["data"]
    with _CACHE_LOCK:
        now = time.time()
        version = mirror_version()
        cache_is_fresh = (
            _CACHE["data"] is not None
            and _CACHE["mirror_version"] == version
            and now - _CACHE["built_at"] < CACHE_TTL_SECONDS
        )
        if not force and cache_is_fresh:
            return _CACHE["data"]
        data = build_index()
        _CACHE["data"] = data
        _CACHE["mirror_version"] = version
        _CACHE["built_at"] = time.time()
        return data


def summary(force: bool = False) -> dict[str, Any]:
    data = get_index(force=force)
    projects = []
    for project in data["projects"]:
        item = {key: value for key, value in project.items() if key not in {"logsByDate", "dates"}}
        projects.append(item)
    return {**data, "projects": projects}


def project_slice(project: dict[str, Any], offset: int = 0, limit: int = 3) -> dict[str, Any]:
    date_count = len(project["dates"])
    safe_offset = max(offset, 0)
    safe_limit = min(max(limit, 1), 120)
    dates = project["dates"][safe_offset : safe_offset + safe_limit]
    date_keys = {item["date"] for item in dates}
    payload = {key: value for key, value in project.items() if key not in {"dates", "logsByDate"}}
    payload["dates"] = dates
    payload["logsByDate"] = {
        day: [
            {key: value for key, value in item.items() if key != "highlights"}
            for item in project["logsByDate"].get(day, [])
        ]
        for day in date_keys
    }
    payload["dateOffset"] = safe_offset
    payload["loadedDateCount"] = min(safe_offset + len(dates), date_count)
    payload["hasMoreDates"] = safe_offset + len(dates) < date_count
    return payload


def project_detail(project_id: str, offset: int = 0, limit: int = 3, force: bool = False) -> dict[str, Any] | None:
    for project in get_index(force=force)["projects"]:
        if project["id"] == project_id:
            return project_slice(project, offset, limit)
    return None


def resolve_log(project_id: str, rel_path: str) -> Path:
    config = load_config()
    project_cfg = next((item for item in config["projects"] if item["id"] == project_id), None)
    if project_cfg is None:
        raise FileNotFoundError(project_id)
    mirror = (ROOT / project_cfg["mirror"]).resolve()
    target = (mirror / rel_path).resolve()
    target.relative_to(mirror)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    return target


def tail_log(project_id: str, rel_path: str, lines: int = 240) -> dict[str, Any]:
    safe_lines = min(max(lines, 20), 1000)
    path = resolve_log(project_id, rel_path)
    stat = path.stat()
    max_bytes = max(80_000, safe_lines * 700)
    with path.open("rb") as fh:
        if stat.st_size > max_bytes:
            fh.seek(stat.st_size - max_bytes)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    parts = text.splitlines()
    if stat.st_size > max_bytes and parts:
        parts = parts[1:]
    tail = "\n".join(parts[-safe_lines:])
    return {
        "project": project_id,
        "path": rel_path,
        "name": path.name,
        "lines": safe_lines,
        "size": stat.st_size,
        "sizeLabel": human_bytes(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "content": tail,
    }
