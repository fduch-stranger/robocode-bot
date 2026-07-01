import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot


class DebugLogger:
    def __init__(self, bot: Bot, log_name: str, sample_interval: int = 25) -> None:
        self._bot = bot
        self._stream = self._open_log(log_name)
        self._telemetry = TelemetryRecorder.open(bot, log_name)
        self._sample_interval = sample_interval
        self._last_sample_turn = -1

    def log(self, event: str, **fields: object) -> None:
        if self._stream is not None:
            payload = " ".join(f"{key}={value}" for key, value in fields.items())
            self._stream.write(f"turn={self._bot.turn_number} event={event} {payload}\n")
            self._stream.flush()
        if self._telemetry is not None:
            self._telemetry.write(event, fields)

    def sample(self, event: str, **fields: object) -> None:
        if self._bot.turn_number - self._last_sample_turn < self._sample_interval:
            return
        self.log(event, **fields)
        self._last_sample_turn = self._bot.turn_number

    @staticmethod
    def _open_log(log_name: str) -> TextIO | None:
        if os.environ.get("ROBOCODE_DEBUG") != "1":
            return None
        log_dir = Path(os.environ.get("ROBOCODE_LOG_DIR", "."))
        log_dir.mkdir(parents=True, exist_ok=True)
        return (log_dir / f"{log_name}-{os.getpid()}.log").open("w", encoding="utf-8")


class TelemetryRecorder:
    _server_start_checked = False

    def __init__(self, bot: Bot, bot_name: str, stream: TextIO) -> None:
        self._bot = bot
        self._bot_name = bot_name
        self._stream = stream
        self.write("telemetry.session", {"pid": os.getpid()})

    @classmethod
    def open(cls, bot: Bot, bot_name: str) -> "TelemetryRecorder | None":
        if os.environ.get("ROBOCODE_TELEMETRY") != "1":
            return None

        telemetry_dir = Path(os.environ.get("ROBOCODE_TELEMETRY_DIR", "battle-results/telemetry/live"))
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        cls._maybe_start_viewer(telemetry_dir)
        stream = (telemetry_dir / f"{bot_name}-{os.getpid()}.jsonl").open("a", encoding="utf-8")
        return cls(bot, bot_name, stream)

    def write(self, event: str, fields: dict[str, object]) -> None:
        record = {
            "schema": 1,
            "ts": round(time.time(), 3),
            "pid": os.getpid(),
            "bot": self._bot_name,
            "turn": self._safe_number("turn_number"),
            "event": event,
            "state": self._state(),
            "fields": self._json_safe(fields),
        }
        self._stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        self._stream.flush()

    def _state(self) -> dict[str, object]:
        return {
            "x": self._safe_number("x"),
            "y": self._safe_number("y"),
            "energy": self._safe_number("energy"),
            "direction": self._safe_number("direction"),
            "gun_direction": self._safe_number("gun_direction"),
            "radar_direction": self._safe_number("radar_direction"),
            "speed": self._safe_number("speed"),
            "target_speed": self._safe_number("target_speed"),
            "turn_rate": self._safe_number("turn_rate"),
            "gun_turn_rate": self._safe_number("gun_turn_rate"),
            "radar_turn_rate": self._safe_number("radar_turn_rate"),
            "gun_heat": self._safe_number("gun_heat"),
            "gun_cooling_rate": self._safe_number("gun_cooling_rate"),
            "enemy_count": self._safe_number("enemy_count"),
            "arena_width": self._safe_number("arena_width"),
            "arena_height": self._safe_number("arena_height"),
        }

    def _safe_number(self, name: str) -> int | float | None:
        try:
            value = getattr(self._bot, name, None)
        except Exception:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)) and math.isfinite(value):
            return round(value, 3)
        return None

    @classmethod
    def _maybe_start_viewer(cls, telemetry_dir: Path) -> None:
        if cls._server_start_checked:
            return
        cls._server_start_checked = True
        if os.environ.get("ROBOCODE_TELEMETRY_AUTOSTART") != "1":
            return

        root_dir = Path(os.environ.get("ROBOCODE_TELEMETRY_ROOT", Path.cwd()))
        server_path = root_dir / "tools" / "telemetry_viewer" / "server.py"
        if not server_path.exists():
            return

        host = os.environ.get("ROBOCODE_TELEMETRY_HOST", "127.0.0.1")
        port = os.environ.get("ROBOCODE_TELEMETRY_PORT", "8765")
        lock_path = telemetry_dir / "telemetry-viewer.lock"
        cls._remove_stale_lock(lock_path)
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return

        log_path = telemetry_dir / "telemetry-viewer.log"
        log_stream = log_path.open("a", encoding="utf-8")
        args = [
            sys.executable,
            str(server_path),
            "--dir",
            str(telemetry_dir),
            "--host",
            host,
            "--port",
            port,
        ]
        if os.environ.get("ROBOCODE_TELEMETRY_PORT_FALLBACK", "1") == "1":
            args.append("--fallback-port")
        if os.environ.get("ROBOCODE_TELEMETRY_OPEN") == "1":
            args.append("--open")
        try:
            process = subprocess.Popen(args, stdout=log_stream, stderr=subprocess.STDOUT, start_new_session=True)
            os.write(lock_fd, str(process.pid).encode("ascii"))
        except OSError:
            lock_path.unlink(missing_ok=True)
        finally:
            os.close(lock_fd)

    @staticmethod
    def _remove_stale_lock(lock_path: Path) -> None:
        if not lock_path.exists():
            return
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
        except (OSError, ValueError):
            lock_path.unlink(missing_ok=True)

    @classmethod
    def _json_safe(cls, value: object) -> object:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return round(value, 6) if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        return str(value)
