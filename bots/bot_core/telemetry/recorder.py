import atexit
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import TextIO

from robocode_tank_royale.bot_api import Bot
from robocode_tank_royale.bot_api.bot_exception import BotException

from bot_core.async_writer import AsyncItemWriter, SyncItemWriter


class TelemetryRecorder:
    _server_start_checked = False

    def __init__(self, bot: Bot, bot_name: str, stream: TextIO, *, sync: bool | None = None, queue_size: int | None = None) -> None:
        self._bot = bot
        self._bot_name = bot_name
        self._closed = False
        self._writer = self._build_writer(stream, sync=sync, queue_size=queue_size)
        self._atexit_callback = self.close
        atexit.register(self._atexit_callback)
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
        if self._closed:
            return
        self._writer.submit(self._record(event, fields))

    def close(self) -> None:
        if self._closed:
            return
        dropped_count = self._writer.dropped_count
        if dropped_count:
            self._writer.submit_blocking(self._record("telemetry.dropped", {"count": dropped_count}))
        self._closed = True
        self._writer.close()
        try:
            atexit.unregister(self._atexit_callback)
        except ValueError:
            pass

    def __enter__(self) -> "TelemetryRecorder":
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _record(self, event: str, fields: dict[str, object]) -> dict[str, object]:
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
        return record

    @staticmethod
    def _build_writer(stream: TextIO, *, sync: bool | None, queue_size: int | None) -> AsyncItemWriter | SyncItemWriter:
        if sync is None:
            sync = os.environ.get("ROBOCODE_TELEMETRY_SYNC") == "1"
        if sync:
            return SyncItemWriter(stream, TelemetryRecorder._encode_record)
        if queue_size is None:
            queue_size = TelemetryRecorder._int_env("ROBOCODE_TELEMETRY_QUEUE_SIZE", 16384)
        return AsyncItemWriter(
            stream,
            TelemetryRecorder._encode_record,
            queue_size=queue_size,
            thread_name="robocode-telemetry-writer",
        )

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
        except (AttributeError, BotException, RuntimeError, TypeError, ValueError):
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
        return f"<{type(value).__name__}>"

    @staticmethod
    def _encode_record(record: object) -> str:
        return json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default
