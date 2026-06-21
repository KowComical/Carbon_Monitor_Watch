from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
MARKER = ROOT / "log_mirror" / ".last_sync"
RSYNC_FLAGS = ["-rt", "--delete", "--no-owner", "--no-group", "--no-perms", "--omit-dir-times"]
WINDOW_DAYS = 14
LOG_SUFFIXES = {".log", ".md", ".out", ".txt"}
LOG_SUFFIX_PRIORITY = {".md": 4, ".log": 3, ".out": 2, ".txt": 1}
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import scanner
from build_static_data import build, date_cutoff


def sync_sources() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    for project in config["projects"]:
        dest = ROOT / project["mirror"]
        dest.mkdir(parents=True, exist_ok=True)
        source = project["source"].rstrip("/") + "/"
        if project.get("host"):
            source = f"{project['host']}:{source}"
        cmd = ["rsync", *RSYNC_FLAGS, source, str(dest) + "/"]
        print(f"Syncing {project['name']} from {source}")
        subprocess.run(cmd, check=True)


def remove_empty_dirs(root: Path) -> int:
    removed = 0
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            path.rmdir()
            removed += 1
        except OSError:
            pass
    return removed


def prune_superseded_logs(root: Path) -> dict[str, int]:
    groups: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in LOG_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        groups.setdefault(rel.with_suffix("").as_posix(), []).append(path)

    deleted_files = 0
    deleted_bytes = 0
    for paths in groups.values():
        if len(paths) < 2:
            continue
        keeper = max(
            paths,
            key=lambda item: (
                LOG_SUFFIX_PRIORITY.get(item.suffix.lower(), 0),
                item.stat().st_mtime,
            ),
        )
        for path in paths:
            if path == keeper:
                continue
            try:
                deleted_bytes += path.stat().st_size
                path.unlink()
                deleted_files += 1
            except OSError as exc:
                print(f"Failed to delete superseded log {path}: {exc}")
    return {"deletedFiles": deleted_files, "deletedBytes": deleted_bytes}


def prune_old_logs(days: int) -> dict[str, int | str | None]:
    index = scanner.get_index(force=True)
    cutoff = date_cutoff(index, days)
    if cutoff is None:
        return {"deletedFiles": 0, "deletedBytes": 0, "deletedDirs": 0, "cutoffDate": None}

    deleted_files = 0
    deleted_bytes = 0
    deleted_dirs = 0
    superseded_files = 0
    superseded_bytes = 0
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    mirrors = {project["id"]: (ROOT / project["mirror"]).resolve() for project in config["projects"]}

    for project in index["projects"]:
        mirror = mirrors.get(project["id"])
        if mirror is None:
            continue
        for items in project["logsByDate"].values():
            for item in items:
                if item["date"] >= cutoff:
                    continue
                target = (mirror / item["path"]).resolve()
                try:
                    target.relative_to(mirror)
                except ValueError:
                    continue
                if not target.is_file() or target.suffix.lower() not in LOG_SUFFIXES:
                    continue
                try:
                    deleted_bytes += target.stat().st_size
                    target.unlink()
                    deleted_files += 1
                except OSError as exc:
                    print(f"Failed to delete {target}: {exc}")
        superseded = prune_superseded_logs(mirror)
        superseded_files += superseded["deletedFiles"]
        superseded_bytes += superseded["deletedBytes"]
        deleted_dirs += remove_empty_dirs(mirror)

    return {
        "deletedFiles": deleted_files,
        "deletedBytes": deleted_bytes,
        "deletedDirs": deleted_dirs,
        "supersededFiles": superseded_files,
        "supersededBytes": superseded_bytes,
        "cutoffDate": cutoff,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--prune-only", action="store_true")
    args = parser.parse_args()

    if not args.prune_only:
        sync_sources()

    prune = prune_old_logs(args.days)
    print(
        "Pruned "
        f"{prune['deletedFiles']} old log files before {prune['cutoffDate']} "
        f"({scanner.human_bytes(int(prune['deletedBytes']))})."
    )
    print(
        "Pruned "
        f"{prune['supersededFiles']} superseded log files "
        f"({scanner.human_bytes(int(prune['supersededBytes']))})."
    )
    MARKER.write_text("Log mirror sync complete.\n", encoding="utf-8")
    build(days=args.days)
    print("Log mirror sync complete.")


if __name__ == "__main__":
    main()
