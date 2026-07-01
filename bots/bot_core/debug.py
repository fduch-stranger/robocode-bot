import atexit
import os
from collections import OrderedDict
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot

from bot_core.async_writer import AsyncItemWriter, SyncItemWriter
from bot_core.telemetry import TelemetryRecorder


class DebugLogger:
    def __init__(self, bot: Bot, log_name: str, sample_interval: int = 25) -> None:
        self._bot = bot
        self._stream = self._open_log(log_name)
        self._log_writer = self._build_log_writer(self._stream)
        self._telemetry = TelemetryRecorder.open(bot, log_name)
        self._sample_interval = sample_interval
        self._last_sample_turn = -1
        self._closed = False
        self._atexit_callback = self.close
        atexit.register(self._atexit_callback)

    def log(self, event: str, **fields: object) -> None:
        if self._log_writer is not None:
            payload = " ".join(f"{key}={value}" for key, value in fields.items())
            self._log_writer.submit(f"turn={self._bot.turn_number} event={event} {payload}\n")
        if self._telemetry is not None:
            self._telemetry.write(event, fields)

    def sample(self, event: str, **fields: object) -> None:
        if self._bot.turn_number - self._last_sample_turn < self._sample_interval:
            return
        self.log(event, **fields)
        self._last_sample_turn = self._bot.turn_number

    def close(self) -> None:
        if self._closed:
            return
        if self._log_writer is not None:
            dropped_count = self._log_writer.dropped_count
            if dropped_count:
                self._log_writer.submit_blocking(f"turn={self._bot.turn_number} event=debug.dropped count={dropped_count}\n")
            self._log_writer.close()
        if self._telemetry is not None:
            self._telemetry.close()
        self._closed = True
        try:
            atexit.unregister(self._atexit_callback)
        except ValueError:
            pass

    @staticmethod
    def _open_log(log_name: str) -> TextIO | None:
        if os.environ.get("ROBOCODE_DEBUG") != "1":
            return None
        log_dir = Path(os.environ.get("ROBOCODE_LOG_DIR", "."))
        log_dir.mkdir(parents=True, exist_ok=True)
        return (log_dir / f"{log_name}-{os.getpid()}.log").open("w", encoding="utf-8")

    @staticmethod
    def _build_log_writer(stream: TextIO | None) -> AsyncItemWriter | SyncItemWriter | None:
        if stream is None:
            return None
        if os.environ.get("ROBOCODE_DEBUG_SYNC") == "1":
            return SyncItemWriter(stream, DebugLogger._encode_log_line)
        return AsyncItemWriter(
            stream,
            DebugLogger._encode_log_line,
            queue_size=DebugLogger._int_env("ROBOCODE_DEBUG_QUEUE_SIZE", 8192),
            thread_name="robocode-debug-log-writer",
        )

    @staticmethod
    def _encode_log_line(line: object) -> str:
        return str(line)

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default


class FiredBulletTracker:
    def __init__(self, max_records: int = 240) -> None:
        self._max_records = max_records
        self._records: OrderedDict[str, dict[str, object]] = OrderedDict()

    def record(self, bullet_id: object, **fields: object) -> dict[str, object]:
        key = self._key(bullet_id)
        if key is None:
            return {}
        record = {field: value for field, value in fields.items() if value is not None}
        self._records[key] = record
        self._records.move_to_end(key)
        while len(self._records) > self._max_records:
            self._records.popitem(last=False)
        return dict(record)

    def fields_for(self, bullet_id: object) -> dict[str, object]:
        key = self._key(bullet_id)
        if key is None:
            return {}
        record = self._records.get(key, {})
        if record:
            self._records.move_to_end(key)
        return dict(record)

    @staticmethod
    def _key(bullet_id: object) -> str | None:
        if bullet_id is None:
            return None
        return str(bullet_id)
