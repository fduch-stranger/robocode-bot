from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.position import drive_command_to_destination


@dataclass(frozen=True)
class MovementCommand:
    mode: str
    turn: float
    speed: float
    strafe_offset: float = 0.0
    telemetry_fields: dict[str, object] = field(default_factory=dict)
    direction_update: int | None = None

    @classmethod
    def strafe(
        cls,
        mode: str,
        body_bearing: float,
        strafe_offset: float,
        direction: int,
        speed: float,
        **telemetry_fields: object,
    ) -> "MovementCommand":
        return cls(
            mode=mode,
            turn=body_bearing + strafe_offset * direction,
            speed=speed,
            strafe_offset=strafe_offset,
            telemetry_fields=telemetry_fields,
        )

    @classmethod
    def drive_to_destination(
        cls,
        bot: Bot,
        x: float,
        y: float,
        speed: float,
        mode: str,
        strafe_offset: float = 0.0,
        direction_update: int | None = None,
        **telemetry_fields: object,
    ) -> "MovementCommand":
        turn, target_speed = drive_command_to_destination(bot, x, y, speed)
        return cls(
            mode=mode,
            turn=turn,
            speed=target_speed,
            strafe_offset=strafe_offset,
            telemetry_fields=telemetry_fields,
            direction_update=direction_update,
        )

    def apply(self, bot: Bot) -> None:
        bot.target_speed = self.speed
        bot.set_turn_left(self.turn)
