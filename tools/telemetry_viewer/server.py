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
    session_generation_gap_seconds = 5.0
    reset_generation_gap_seconds = 2.0
    _cache_lock = threading.Lock()
    _event_cache: deque[dict[str, object]] = deque(maxlen=event_limit)
    _positions: dict[str, int] = {}
    _active_files: set[str] = set()
    _next_cursor = 1
    _generation = 1
    _battle_reset_group_timestamp: float | None = None

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

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _events(self, query: dict[str, list[str]]) -> dict[str, object]:
        limit = _int_query(query, "limit", 5000, 100, 50000)
        cursor = _int_query(query, "cursor", 0, 0, 2**63 - 1)
        generation = _int_query(query, "generation", 0, 0, 2**63 - 1)
        with self._cache_lock:
            handler = type(self)
            files = self._files()
            self._scan_files(files)
            latest_cursor = handler._next_cursor - 1
            generation_changed = bool(generation and generation != handler._generation)
            if cursor and not generation_changed:
                events = [event for event in handler._event_cache if int(event.get("cursor", 0)) > cursor]
            else:
                events = list(handler._event_cache)
            events = events[-limit:]
        return {
            "dir": str(self.telemetry_dir),
            "files": files,
            "cursor": latest_cursor,
            "generation": handler._generation,
            "events": events,
            "truncated": bool(generation_changed or (cursor and events and int(events[0].get("cursor", 0)) > cursor + 1)),
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
            handler._active_files.clear()
            handler._next_cursor = 1
            handler._generation += 1
        return {"ok": not errors, "reset": reset, "errors": errors, "cursor": 0, "generation": handler._generation}

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
            self._maybe_start_new_generation(event)
            if not self._accept_event(event):
                continue
            event["cursor"] = handler._next_cursor
            handler._next_cursor += 1
            handler._event_cache.append(event)

    def _accept_event(self, event: dict[str, object]) -> bool:
        handler = type(self)
        file_name = event.get("file")
        if event.get("event") in {"telemetry.session", "battle.reset"}:
            if isinstance(file_name, str):
                handler._active_files.add(file_name)
            return True
        return not handler._active_files or file_name in handler._active_files

    def _maybe_start_new_generation(self, event: dict[str, object]) -> None:
        event_name = event.get("event")
        if event_name == "battle.reset":
            self._maybe_start_battle_generation(event)
            return
        if event_name != "telemetry.session":
            return

        handler = type(self)
        if not handler._event_cache:
            return

        bot = event.get("bot")
        pid = event.get("pid")
        fields = event.get("fields")
        if pid in (None, "") and isinstance(fields, dict):
            pid = fields.get("pid")
        timestamp = _numeric(event.get("ts"))
        latest_session = _latest_session(handler._event_cache)
        has_battle_events = any(cached.get("event") != "telemetry.session" for cached in handler._event_cache)
        has_previous_bot_session = any(
            cached.get("event") == "telemetry.session"
            and cached.get("bot") == bot
            and _event_pid(cached) != pid
            for cached in handler._event_cache
        )
        session_gap = (
            timestamp is not None
            and latest_session is not None
            and timestamp - latest_session > handler.session_generation_gap_seconds
        )
        if has_battle_events or has_previous_bot_session or session_gap:
            self._start_new_generation()

    def _maybe_start_battle_generation(self, event: dict[str, object]) -> None:
        handler = type(self)
        timestamp = _numeric(event.get("ts"))
        if not handler._event_cache:
            handler._battle_reset_group_timestamp = timestamp
            return

        if self._in_current_battle_reset_group(timestamp):
            return

        if any(cached.get("event") != "battle.reset" for cached in handler._event_cache):
            self._start_new_generation()
        handler._battle_reset_group_timestamp = timestamp

    def _in_current_battle_reset_group(self, timestamp: float | None) -> bool:
        handler = type(self)
        group_timestamp = handler._battle_reset_group_timestamp
        if group_timestamp is None:
            return all(cached.get("event") == "battle.reset" for cached in handler._event_cache)
        if timestamp is None:
            return True
        return abs(timestamp - group_timestamp) <= handler.reset_generation_gap_seconds

    def _start_new_generation(self) -> None:
        handler = type(self)
        if not handler._event_cache:
            return
        handler._event_cache.clear()
        handler._active_files.clear()
        handler._battle_reset_group_timestamp = None
        handler._generation += 1

    def _write_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _int_query(query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(query.get(name, [str(default)])[0])
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _numeric(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _event_pid(event: dict[str, object]) -> object:
    pid = event.get("pid")
    fields = event.get("fields")
    if pid in (None, "") and isinstance(fields, dict):
        pid = fields.get("pid")
    return pid


def _latest_session(events: deque[dict[str, object]]) -> float | None:
    latest: float | None = None
    for event in events:
        if event.get("event") != "telemetry.session":
            continue
        timestamp = _numeric(event.get("ts"))
        if timestamp is not None and (latest is None or timestamp > latest):
            latest = timestamp
    return latest


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
