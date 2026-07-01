from dataclasses import dataclass


@dataclass(frozen=True)
class MovementWaveFeatures:
    lateral_velocity: float = 0.0
    advancing_velocity: float = 0.0
    bullet_flight_time: float = 0.0
    acceleration: float = 0.0
    direction_change_age: int = 0
    decel_age: int = 0
    wall_distance: float = 0.0


@dataclass
class MovementWave:
    target_id: int
    source_x: float
    source_y: float
    direct_bearing: float
    lateral_direction: int
    bullet_speed: float
    max_escape_angle_positive: float
    max_escape_angle_negative: float
    fired_turn: int
    distance_bucket: int
    kind: str = "confirmed"
    expected_confidence: float = 1.0
    features: MovementWaveFeatures = MovementWaveFeatures()


@dataclass(frozen=True)
class ShadowBullet:
    bullet_id: str
    source_x: float
    source_y: float
    direction: float
    bullet_speed: float
    fired_turn: int


class MovementWaveStore:
    def __init__(self) -> None:
        self.waves: list[MovementWave] = []

    def add(self, wave: MovementWave) -> None:
        self.waves.append(wave)

    def replace(self, waves: list[MovementWave]) -> None:
        self.waves[:] = waves

    def remove(self, wave: MovementWave) -> None:
        self.replace([candidate for candidate in self.waves if candidate is not wave])

    def remove_target(self, target_id: int) -> None:
        self.replace([wave for wave in self.waves if wave.target_id != target_id])

    def remove_recent_expected(self, target_id: int, turn_number: int, max_age: int) -> None:
        self.replace(
            [
                wave
                for wave in self.waves
                if not (
                    wave.target_id == target_id
                    and wave.kind == "expected"
                    and 0 <= turn_number - wave.fired_turn <= max_age
                )
            ]
        )

    def for_target(self, target_id: int) -> list[MovementWave]:
        return [wave for wave in self.waves if wave.target_id == target_id]

    def matching_target_speed(self, target_id: int, bullet_speed: float, tolerance: float) -> list[MovementWave]:
        return [
            wave
            for wave in self.waves
            if wave.target_id == target_id and abs(wave.bullet_speed - bullet_speed) <= tolerance
        ]

    def clear_round_state(self) -> None:
        self.waves.clear()
