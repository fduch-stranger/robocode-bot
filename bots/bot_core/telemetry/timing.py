from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from bot_core.telemetry.sink import TelemetrySink


@dataclass(frozen=True)
class TurnTimingRecord:
    turn: int
    decision_elapsed_us: int
    turn_timeout_us: int | None
    time_left_us_before_go: int | None
    severity: str


class TurnTimingTelemetry:
    def __init__(
        self,
        sink: TelemetrySink,
        *,
        sample_interval: int = 25,
        warn_elapsed_us: int = 2500,
        danger_elapsed_us: int = 4000,
        critical_time_left_us: int = 500,
    ) -> None:
        self._sink = sink
        self._sample_interval = max(1, sample_interval)
        self._warn_elapsed_us = warn_elapsed_us
        self._danger_elapsed_us = danger_elapsed_us
        self._critical_time_left_us = critical_time_left_us
        self._last_record: TurnTimingRecord | None = None

    @staticmethod
    def begin() -> int:
        return time.perf_counter_ns()

    @property
    def last_record(self) -> TurnTimingRecord | None:
        return self._last_record

    def record_turn(self, bot: Any, start_ns: int, **fields: object) -> TurnTimingRecord:
        elapsed_us = max(0, (time.perf_counter_ns() - start_ns) // 1000)
        turn_timeout_us = _safe_int_property(bot, "turn_timeout")
        time_left_us = _safe_int_property(bot, "time_left")
        turn = _safe_int_property(bot, "turn_number") or 0
        severity = self._severity(elapsed_us, time_left_us, turn_timeout_us)
        record = TurnTimingRecord(
            turn=turn,
            decision_elapsed_us=elapsed_us,
            turn_timeout_us=turn_timeout_us,
            time_left_us_before_go=time_left_us,
            severity=severity,
        )
        self._last_record = record

        if severity != "ok" or turn % self._sample_interval == 0:
            self._sink.log(
                "bot.turn_timing",
                decision_elapsed_us=elapsed_us,
                turn_timeout_us=turn_timeout_us,
                time_left_us_before_go=time_left_us,
                severity=severity,
                **fields,
            )
        return record

    def record_skipped_turn(self, bot: Any, event: Any, **fields: object) -> None:
        last = self._last_record
        self._sink.log(
            "bot.skipped_turn",
            skipped_turn=getattr(event, "turn_number", None),
            current_turn=_safe_int_property(bot, "turn_number"),
            last_decision_elapsed_us=last.decision_elapsed_us if last is not None else None,
            last_time_left_us_before_go=last.time_left_us_before_go if last is not None else None,
            turn_timeout_us=_safe_int_property(bot, "turn_timeout"),
            time_left_us=_safe_int_property(bot, "time_left"),
            **fields,
        )

    def _severity(self, elapsed_us: int, time_left_us: int | None, turn_timeout_us: int | None) -> str:
        warn_elapsed_us = self._warn_elapsed_us
        danger_elapsed_us = self._danger_elapsed_us
        critical_time_left_us = self._critical_time_left_us
        if turn_timeout_us is not None and turn_timeout_us > 0:
            warn_elapsed_us = max(warn_elapsed_us, turn_timeout_us // 2)
            danger_elapsed_us = max(danger_elapsed_us, int(turn_timeout_us * 0.8))
            critical_time_left_us = max(critical_time_left_us, turn_timeout_us // 10)
        if time_left_us is not None and time_left_us <= critical_time_left_us:
            return "critical"
        if elapsed_us >= danger_elapsed_us:
            return "danger"
        if elapsed_us >= warn_elapsed_us:
            return "warn"
        return "ok"


def _safe_int_property(obj: Any, name: str) -> int | None:
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["TurnTimingRecord", "TurnTimingTelemetry"]
