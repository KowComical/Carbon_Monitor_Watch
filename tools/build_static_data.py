from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATIC_DATA = ROOT / "static" / "data"
TAIL_LINES = 200

sys.path.insert(0, str(ROOT))

import scanner  # noqa: E402


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def date_cutoff(index: dict[str, Any], days: int) -> str | None:
    latest = index.get("latestDate")
    if not latest:
        return None
    latest_day = datetime.strptime(latest, "%Y-%m-%d").date()
    return (latest_day - timedelta(days=days - 1)).isoformat()


def log_data_name(project_id: str, rel_path: str) -> str:
    digest = hashlib.sha1(f"{project_id}:{rel_path}".encode("utf-8")).hexdigest()[:16]
    return f"{digest}.json"


def strip_log_for_list(item: dict[str, Any], data_path: str) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"highlights"}
    } | {"dataPath": data_path}


def merge_log_content(project_id: str, items: list[dict[str, Any]]) -> str:
    chunks = []
    for item in sorted(items, key=lambda log: (log["mtime"], log["path"])):
        tail = scanner.tail_log(project_id, item["path"], TAIL_LINES)
        chunks.append(f"## {item['name']}\n\n{tail.get('content', '')}".rstrip())
    return "\n\n".join(chunks)


def merged_log_for_day(project: dict[str, Any], day: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(items, key=lambda item: (item["mtime"], item["path"]))
    latest = ordered[-1]
    status = scanner.aggregate_status(ordered)
    rel_path = f"{day[:4]}/{day[5:7]}/combined-{day}.md"
    file_name = log_data_name(project["id"], rel_path)
    data_path = f"data/logs/{project['id']}/{file_name}"
    content = merge_log_content(project["id"], ordered)
    total_size = sum(item["size"] for item in ordered)
    payload = {
        "project": project["id"],
        "path": rel_path,
        "name": f"combined-{day}.md",
        "lines": TAIL_LINES,
        "size": total_size,
        "sizeLabel": scanner.human_bytes(total_size),
        "modified": latest["modified"],
        "content": content,
    }
    dump_json(STATIC_DATA / "logs" / project["id"] / file_name, payload)
    return {
        "path": rel_path,
        "name": f"combined-{day}.md",
        "date": day,
        "status": status,
        "size": total_size,
        "sizeLabel": scanner.human_bytes(total_size),
        "mtime": latest["mtime"],
        "modified": latest["modified"],
        "errors": sum(item["errors"] for item in ordered),
        "warnings": sum(item["warnings"] for item in ordered),
        "okSignals": sum(item["okSignals"] for item in ordered),
        "lastLine": latest["lastLine"],
        "dataPath": data_path,
    }


def static_logs_for_day(project: dict[str, Any], day: str) -> list[dict[str, Any]]:
    items = project["logsByDate"].get(day, [])
    if len(items) > 1:
        return [merged_log_for_day(project, day, items)]

    logs = []
    for item in items:
        file_name = log_data_name(project["id"], item["path"])
        data_path = f"data/logs/{project['id']}/{file_name}"
        tail = scanner.tail_log(project["id"], item["path"], TAIL_LINES)
        dump_json(STATIC_DATA / "logs" / project["id"] / file_name, tail)
        logs.append(strip_log_for_list(item, data_path))
    return logs


def project_for_static(project: dict[str, Any], cutoff: str | None) -> dict[str, Any]:
    dates = [
        item
        for item in project["dates"]
        if cutoff is None or item["date"] >= cutoff
    ]
    date_keys = {item["date"] for item in dates}
    logs_by_date: dict[str, list[dict[str, Any]]] = {}

    for day in date_keys:
        logs_by_date[day] = static_logs_for_day(project, day)

    dates = [
        {
            **item,
            "count": len(logs_by_date.get(item["date"], [])),
            "status": scanner.aggregate_status(logs_by_date.get(item["date"], [])),
            "errors": sum(log["errors"] for log in logs_by_date.get(item["date"], [])),
            "warnings": sum(log["warnings"] for log in logs_by_date.get(item["date"], [])),
            "latestModified": max(
                (log["modified"] for log in logs_by_date.get(item["date"], [])),
                default=item["latestModified"],
            ),
            "mtime": max(
                (log["mtime"] for log in logs_by_date.get(item["date"], [])),
                default=item["mtime"],
            ),
        }
        for item in dates
    ]

    latest_date = dates[0]["date"] if dates else None
    latest_items = logs_by_date.get(latest_date, []) if latest_date else []
    latest_log = latest_items[0] if latest_items else None
    total_bytes = sum(item["size"] for items in logs_by_date.values() for item in items)

    payload = {
        key: value
        for key, value in project.items()
        if key not in {"dates", "logsByDate", "totalBytes", "totalSize", "fileCount", "dateCount", "latestDate", "latestFile", "latestLine", "latestErrors", "latestWarnings"}
    }
    payload.update(
        {
            "latestDate": latest_date,
            "latestFile": latest_log["path"] if latest_log else None,
            "latestLine": latest_log["lastLine"] if latest_log else "",
            "fileCount": sum(len(items) for items in logs_by_date.values()),
            "dateCount": len(dates),
            "totalBytes": total_bytes,
            "totalSize": scanner.human_bytes(total_bytes),
            "latestErrors": sum(item["errors"] for item in latest_items),
            "latestWarnings": sum(item["warnings"] for item in latest_items),
            "dates": dates,
            "logsByDate": logs_by_date,
            "dateOffset": 0,
            "loadedDateCount": len(dates),
            "hasMoreDates": False,
        }
    )
    return payload


def build(days: int) -> dict[str, Any]:
    index = scanner.get_index(force=True)
    cutoff = date_cutoff(index, days)
    if STATIC_DATA.exists():
        shutil.rmtree(STATIC_DATA)
    STATIC_DATA.mkdir(parents=True, exist_ok=True)

    projects = []
    for project in index["projects"]:
        static_project = project_for_static(project, cutoff)
        dump_json(STATIC_DATA / "projects" / f"{project['id']}.json", static_project)
        projects.append({key: value for key, value in static_project.items() if key not in {"dates", "logsByDate"}})

    latest_dates = [project["latestDate"] for project in projects if project["latestDate"]]
    summary = {
        "appName": index.get("appName", "Carbon Monitor Watch"),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "windowDays": days,
        "cutoffDate": cutoff,
        "projectCount": len(projects),
        "fileCount": sum(project["fileCount"] for project in projects),
        "dateCount": sum(project["dateCount"] for project in projects),
        "totalBytes": sum(project["totalBytes"] for project in projects),
        "totalSize": scanner.human_bytes(sum(project["totalBytes"] for project in projects)),
        "latestDate": max(latest_dates) if latest_dates else None,
        "projects": projects,
    }
    dump_json(STATIC_DATA / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    summary = build(args.days)
    print(
        f"Built static data: {summary['projectCount']} projects, "
        f"{summary['fileCount']} log files, cutoff {summary['cutoffDate']}"
    )


if __name__ == "__main__":
    main()
