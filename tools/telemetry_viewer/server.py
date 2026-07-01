#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class TelemetryHandler(SimpleHTTPRequestHandler):
    telemetry_dir: Path
    static_dir: Path
    event_limit = 50000
    _cache_lock = threading.Lock()
    _event_cache: deque[dict[str, object]] = deque(maxlen=event_limit)
    _positions: dict[str, int] = {}
    _next_cursor = 1

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/events":
            self._write_json(self._events(parse_qs(parsed.query)))
            return
        if parsed.path == "/api/health":
            self._write_json({"ok": True, "dir": str(self.telemetry_dir), "files": self._files()})
            return
        if parsed.path == "/api/shutdown":
            self._write_json({"ok": True, "shutdown": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/reset":
            self._write_json(self._reset())
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _events(self, query: dict[str, list[str]]) -> dict[str, object]:
        limit = _int_query(query, "limit", 5000, 100, 50000)
        cursor = _int_query(query, "cursor", 0, 0, 2**63 - 1)
        with self._cache_lock:
            handler = type(self)
            files = self._files()
            self._scan_files(files)
            latest_cursor = handler._next_cursor - 1
            if cursor:
                events = [event for event in handler._event_cache if int(event.get("cursor", 0)) > cursor]
            else:
                events = list(handler._event_cache)
            events = events[-limit:]
        return {
            "dir": str(self.telemetry_dir),
            "files": files,
            "cursor": latest_cursor,
            "events": events,
            "truncated": bool(cursor and events and int(events[0].get("cursor", 0)) > cursor + 1),
        }

    def _files(self) -> list[str]:
        try:
            return sorted(path.name for path in self.telemetry_dir.glob("*.jsonl") if path.is_file())
        except OSError:
            return []

    def _reset(self) -> dict[str, object]:
        reset: list[str] = []
        errors: list[str] = []
        with self._cache_lock:
            handler = type(self)
            for path in self.telemetry_dir.glob("*.jsonl"):
                if not path.is_file():
                    continue
                try:
                    path.write_text("", encoding="utf-8")
                    reset.append(path.name)
                except OSError as error:
                    errors.append(f"{path.name}: {error}")
            handler._event_cache.clear()
            handler._positions.clear()
            handler._next_cursor = 1
        return {"ok": not errors, "reset": reset, "errors": errors, "cursor": 0}

    def _scan_files(self, files: list[str]) -> None:
        handler = type(self)
        current_files = set(files)
        for stale_file in set(handler._positions) - current_files:
            del handler._positions[stale_file]

        batch: list[dict[str, object]] = []
        for file_name in files:
            path = self.telemetry_dir / file_name
            position = handler._positions.get(file_name, 0)
            try:
                size = path.stat().st_size
                if size < position:
                    position = 0
                with path.open("r", encoding="utf-8") as stream:
                    stream.seek(position)
                    for line in stream:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        event["file"] = file_name
                        batch.append(event)
                    handler._positions[file_name] = stream.tell()
            except OSError:
                continue

        batch.sort(key=lambda item: (item.get("ts", 0), item.get("pid", 0), item.get("turn", 0), item.get("file", "")))
        for event in batch:
            event["cursor"] = handler._next_cursor
            handler._next_cursor += 1
            handler._event_cache.append(event)

    def _write_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _int_query(query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(query.get(name, [str(default)])[0])
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve Robocode bot telemetry UI.")
    parser.add_argument("--dir", default="battle-results/telemetry/live", help="Directory containing bot telemetry JSONL files.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Use 0 for a free port.")
    parser.add_argument("--fallback-port", action="store_true", help="Use a free port if the requested port is busy.")
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser.")
    parser.add_argument("--daemon", action="store_true", help="Start the viewer as a detached background process.")
    parser.add_argument("--pid-file", help="Write the detached viewer process id to this file.")
    parser.add_argument("--log-file", help="Write detached viewer output to this file.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.daemon:
        return _start_daemon(args)

    telemetry_dir = Path(args.dir).expanduser().resolve()
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    TelemetryHandler.telemetry_dir = telemetry_dir
    TelemetryHandler.static_dir = Path(__file__).resolve().parent / "static"

    try:
        server = ThreadingHTTPServer((args.host, args.port), TelemetryHandler)
    except OSError:
        if not args.fallback_port or args.port == 0:
            raise
        server = ThreadingHTTPServer((args.host, 0), TelemetryHandler)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    (telemetry_dir / "telemetry-viewer.url").write_text(url + "\n", encoding="utf-8")
    print(f"Telemetry viewer: {url}")
    print(f"Telemetry dir: {telemetry_dir}")
    if args.open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def _start_daemon(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--dir",
        args.dir,
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.fallback_port:
        command.append("--fallback-port")
    if args.open:
        command.append("--open")

    log_path = Path(args.log_file).expanduser().resolve() if args.log_file else Path(os.devnull)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_stream:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    if args.pid_file:
        pid_path = Path(args.pid_file).expanduser().resolve()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(process.pid), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
