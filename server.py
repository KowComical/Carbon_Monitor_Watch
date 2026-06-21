from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import scanner

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def query_int(params: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(params.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        return default


class WatchHandler(BaseHTTPRequestHandler):
    server_version = "CarbonMonitorWatch/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 404) -> None:
        self.send_json({"error": message}, status=status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path == "/api/summary":
                force = params.get("force", ["0"])[0].lower() in {"1", "true", "yes"}
                self.send_json(scanner.summary(force=force))
            elif path.startswith("/api/projects/"):
                project_id = unquote(path.removeprefix("/api/projects/")).strip("/")
                offset = query_int(params, "offset", 0)
                limit = query_int(params, "limit", 3)
                project = scanner.project_detail(project_id, offset, limit)
                if project is None:
                    self.send_error_json("project not found", 404)
                else:
                    self.send_json(project)
            elif path == "/api/log":
                project_id = params.get("project", [""])[0]
                rel_path = params.get("path", [""])[0]
                lines = query_int(params, "lines", 240)
                self.send_json(scanner.tail_log(project_id, rel_path, lines))
            elif path == "/" or path == "/index.html":
                self.serve_file(STATIC / "index.html")
            elif path.startswith("/static/"):
                rel = unquote(path.removeprefix("/static/"))
                self.serve_file((STATIC / rel).resolve())
            elif path in {"/app.js", "/styles.css"} or path.startswith("/data/"):
                rel = unquote(path.removeprefix("/"))
                self.serve_file((STATIC / rel).resolve())
            else:
                self.send_error_json("not found", 404)
        except Exception as exc:
            self.send_error_json(str(exc), 500)

    def serve_file(self, path: Path) -> None:
        root = STATIC.resolve()
        target = path.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), WatchHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Carbon Monitor Watch running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCarbon Monitor Watch stopped.")


if __name__ == "__main__":
    main()
