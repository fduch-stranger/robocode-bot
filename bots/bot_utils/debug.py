import os
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot


class DebugLogger:
    def __init__(self, bot: Bot, log_name: str, sample_interval: int = 25) -> None:
        self._bot = bot
        self._stream = self._open_log(log_name)
        self._sample_interval = sample_interval
        self._last_sample_turn = -1

    def log(self, event: str, **fields: object) -> None:
        if self._stream is None:
            return
        payload = " ".join(f"{key}={value}" for key, value in fields.items())
        self._stream.write(f"turn={self._bot.turn_number} event={event} {payload}\n")
        self._stream.flush()

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
