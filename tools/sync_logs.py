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
        cmd = ["rsync", *RSYNC_FLAGS]
        suffixes = [suffix.lower() for suffix in project.get("log_suffixes", [])]
        if suffixes:
            cmd.append("--include=*/")
            for suffix in suffixes:
                cmd.append(f"--include=*{suffix}")
            cmd.append("--exclude=*")
        cmd.extend([source, str(dest) + "/"])
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


def prune_disallowed_logs(root: Path, allowed_suffixes: set[str]) -> dict[str, int]:
    deleted_files = 0
    deleted_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in LOG_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() in allowed_suffixes:
            continue
        try:
            deleted_bytes += path.stat().st_size
            path.unlink()
            deleted_files += 1
        except OSError as exc:
            print(f"Failed to delete disallowed log {path}: {exc}")
    return {"deletedFiles": deleted_files, "deletedBytes": deleted_bytes}


def prune_superseded_logs(root: Path, allowed_suffixes: set[str]) -> dict[str, int]:
    groups: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
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
        return {
            "deletedFiles": 0,
            "deletedBytes": 0,
            "deletedDirs": 0,
            "supersededFiles": 0,
            "supersededBytes": 0,
            "disallowedFiles": 0,
            "disallowedBytes": 0,
            "cutoffDate": None,
        }

    deleted_files = 0
    deleted_bytes = 0
    deleted_dirs = 0
    superseded_files = 0
    superseded_bytes = 0
    disallowed_files = 0
    disallowed_bytes = 0
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    mirrors = {project["id"]: (ROOT / project["mirror"]).resolve() for project in config["projects"]}
    projects_by_id = {project["id"]: project for project in index["projects"]}

    for project_cfg in config["projects"]:
        mirror = mirrors.get(project_cfg["id"])
        if mirror is None:
            continue
        allowed = {suffix.lower() for suffix in project_cfg.get("log_suffixes", LOG_SUFFIXES)}
        disallowed = prune_disallowed_logs(mirror, allowed)
        disallowed_files += disallowed["deletedFiles"]
        disallowed_bytes += disallowed["deletedBytes"]
        project = projects_by_id.get(project_cfg["id"])
        if project is None:
            deleted_dirs += remove_empty_dirs(mirror)
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
        superseded = prune_superseded_logs(mirror, allowed)
        superseded_files += superseded["deletedFiles"]
        superseded_bytes += superseded["deletedBytes"]
        deleted_dirs += remove_empty_dirs(mirror)

    return {
        "deletedFiles": deleted_files,
        "deletedBytes": deleted_bytes,
        "deletedDirs": deleted_dirs,
        "supersededFiles": superseded_files,
        "supersededBytes": superseded_bytes,
        "disallowedFiles": disallowed_files,
        "disallowedBytes": disallowed_bytes,
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
    print(
        "Pruned "
        f"{prune['disallowedFiles']} disallowed log files "
        f"({scanner.human_bytes(int(prune['disallowedBytes']))})."
    )
    MARKER.write_text("Log mirror sync complete.\n", encoding="utf-8")
    build(days=args.days)
    print("Log mirror sync complete.")


if __name__ == "__main__":
    main()
