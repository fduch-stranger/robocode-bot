import os
from collections import OrderedDict
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot

from bot_core.telemetry import TelemetryRecorder


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
