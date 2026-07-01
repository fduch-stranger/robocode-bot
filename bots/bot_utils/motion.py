from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OwnMotionSnapshot:
    acceleration: float = 0.0
    direction_change_age: int = 0
    decel_age: int = 0


class OwnMotionTracker:
    def __init__(
        self,
        direction_change_threshold: float = 4.0,
        speed_change_threshold: float = 0.55,
        decel_threshold: float = 0.35,
    ) -> None:
        self.direction_change_threshold = direction_change_threshold
        self.speed_change_threshold = speed_change_threshold
        self.decel_threshold = decel_threshold
        self._previous_speed: float | None = None
        self._previous_direction: float | None = None
        self._acceleration = 0.0
        self._last_direction_change_turn = 0
        self._last_decel_turn = 0

    def reset(self, turn_number: int = 0) -> None:
        self._previous_speed = None
        self._previous_direction = None
        self._acceleration = 0.0
        self._last_direction_change_turn = turn_number
        self._last_decel_turn = turn_number

    def update(self, bot: object) -> OwnMotionSnapshot:
        turn_number = int(getattr(bot, "turn_number"))
        speed = float(getattr(bot, "speed"))
        direction = float(getattr(bot, "direction"))
        if self._previous_speed is None:
            self._previous_speed = speed
            self._previous_direction = direction
            self._last_direction_change_turn = turn_number
            self._last_decel_turn = turn_number
            return self.snapshot(turn_number)

        speed_delta = speed - self._previous_speed
        self._acceleration = speed_delta
        previous_direction = self._previous_direction if self._previous_direction is not None else direction
        direction_delta = abs(((direction - previous_direction + 180.0) % 360.0) - 180.0)
        if direction_delta > self.direction_change_threshold or abs(speed_delta) > self.speed_change_threshold:
            self._last_direction_change_turn = turn_number
        if abs(speed) + self.decel_threshold < abs(self._previous_speed):
            self._last_decel_turn = turn_number

        self._previous_speed = speed
        self._previous_direction = direction
        return self.snapshot(turn_number)

    def snapshot(self, turn_number: int) -> OwnMotionSnapshot:
        return OwnMotionSnapshot(
            acceleration=self._acceleration,
            direction_change_age=max(0, turn_number - self._last_direction_change_turn),
            decel_age=max(0, turn_number - self._last_decel_turn),
        )

    def movement_wave_kwargs(self, turn_number: int) -> dict[str, float | int]:
        snapshot = self.snapshot(turn_number)
        return {
            "acceleration": snapshot.acceleration,
            "direction_change_age": snapshot.direction_change_age,
            "decel_age": snapshot.decel_age,
        }
