import math
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to
from bot_core.physics import (
    RobotMovementState,
    bullet_speed_for_power,
    predict_robot_movement,
)
from bot_core.target_snapshot import TargetSnapshot


@dataclass(frozen=True)
class LinearPrediction:
    x: float
    y: float
    ticks: int
    final_speed: float
    wall_hit: bool = False

    @property
    def position(self) -> tuple[float, float]:
        return self.x, self.y


def predict_linear_position(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    field_margin: float,
) -> tuple[float, float]:
    return predict_linear_details(bot, target, firepower, field_margin).position


def predict_linear_details(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    field_margin: float,
) -> LinearPrediction:
    heading = math.radians(target.direction)
    velocity_x = math.cos(heading) * target.speed
    velocity_y = math.sin(heading) * target.speed
    bullet_speed = bullet_speed_for_power(firepower)
    predicted_x = target.x
    predicted_y = target.y
    max_ticks = _max_prediction_ticks(bot, target, bullet_speed)
    ticks_elapsed = 0

    for tick in range(1, max_ticks + 1):
        ticks_elapsed = tick
        predicted_x = clamp(target.x + velocity_x * tick, field_margin, bot.arena_width - field_margin)
        predicted_y = clamp(target.y + velocity_y * tick, field_margin, bot.arena_height - field_margin)
        if bullet_speed * tick >= distance_to(bot, predicted_x, predicted_y):
            break

    return LinearPrediction(
        clamp(predicted_x, field_margin, bot.arena_width - field_margin),
        clamp(predicted_y, field_margin, bot.arena_height - field_margin),
        ticks_elapsed,
        target.speed,
    )


def predict_wall_aware_linear_position(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    field_margin: float,
) -> tuple[float, float]:
    return predict_wall_aware_linear_details(bot, target, firepower, field_margin).position


def predict_wall_aware_linear_details(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    field_margin: float,
) -> LinearPrediction:
    bullet_speed = bullet_speed_for_power(firepower)
    max_ticks = _max_prediction_ticks(bot, target, bullet_speed)
    move_bearing = target.direction if target.speed >= 0.0 else target.direction + 180.0
    state = RobotMovementState(target.x, target.y, target.direction, target.speed)
    wall_hit = False
    ticks_elapsed = 0

    for tick in range(1, max_ticks + 1):
        ticks_elapsed = tick
        previous_speed = state.speed
        state = predict_robot_movement(
            state,
            move_bearing=move_bearing,
            max_speed=abs(target.speed),
            field_margin=field_margin,
            arena_width=bot.arena_width,
            arena_height=bot.arena_height,
        )
        if previous_speed != 0.0 and state.speed == 0.0:
            wall_hit = True
        if bullet_speed * tick >= distance_to(bot, state.x, state.y):
            break

    return LinearPrediction(state.x, state.y, ticks_elapsed, state.speed, wall_hit=wall_hit)


def _max_prediction_ticks(bot: Bot, target: TargetSnapshot, bullet_speed: float) -> int:
    flight_ticks = math.ceil(distance_to(bot, target.x, target.y) / max(0.1, bullet_speed))
    return max(1, min(90, flight_ticks + 32))
