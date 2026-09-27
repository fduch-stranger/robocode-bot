"""``voidious.utils.Enemy`` and ``EnemyDataManager``: the per-enemy record
shared by the gun and movement data managers, plus the engine-event records
the bot adapter builds from Tank Royale events."""
from __future__ import annotations

import math
import sys

from diamond_port.dia_utils import BattleField, Point, RobotState, RobotStateLog
from diamond_port.knn_view import KnnView
from diamond_port.movement_predictor import MovementPredictor
from diamond_port.wave import WaveManager

DEFAULT_ENERGY = 100.0
IS_BULLET_HIT = False
IS_VISIT = True


class ScannedRobotEvent:
    """What ``robocode.ScannedRobotEvent`` gave Diamond, from a Tank Royale scan."""

    __slots__ = ("name", "time", "location", "heading_radians", "velocity", "energy", "distance")

    def __init__(self, name, time: int, location: Point, heading_radians: float, velocity: float, energy: float, distance: float) -> None:
        self.name = name
        self.time = time
        self.location = location
        self.heading_radians = heading_radians
        self.velocity = velocity
        self.energy = energy
        self.distance = distance


class BulletRecord:
    """``robocode.Bullet`` as Diamond reads it: owner name, power and position."""

    __slots__ = ("name", "power", "x", "y", "heading_radians", "bullet_id")

    def __init__(self, name, power: float, x: float, y: float, heading_radians: float, bullet_id: int) -> None:
        self.name = name
        self.power = power
        self.x = x
        self.y = y
        self.heading_radians = heading_radians
        self.bullet_id = bullet_id


def warn(label: str, message: str) -> None:
    print(f"WARNING ({label}): {message}", file=sys.stderr)


class Enemy:
    def __init__(
        self,
        bot_name,
        location: Point,
        distance: float,
        energy: float,
        heading: float,
        velocity: float,
        abs_bearing: float,
        round_num: int,
        time: int,
        battle_field: BattleField,
        predictor: MovementPredictor,
        wave_manager: WaveManager,
    ) -> None:
        self.bot_name = bot_name
        self.abs_bearing = abs_bearing
        self.distance = distance
        self.energy = energy
        self.last_scan_round = round_num
        self.time_alive_together = 1
        self.battle_field = battle_field
        self.predictor = predictor
        self.wave_manager = wave_manager
        self.damage_given = 0.0
        self.alive = True
        self.views: dict[str, KnnView] = {}
        self.state_log = RobotStateLog()
        self.last_scan_state: RobotState | None = None
        self.set_robot_state(RobotState(location, heading, velocity, time))
        self._bot_distances_sq: dict[object, float] = {}

    def init_round(self) -> None:
        self.energy = DEFAULT_ENERGY
        self.distance = 1000.0
        self.alive = True
        self.state_log.clear()
        self.wave_manager.init_round()
        self.clear_distances_sq()

    def add_views(self, views: list[KnnView]) -> None:
        for view in views:
            self.add_view(view)

    def add_view(self, view: KnnView) -> None:
        self.views[view.name] = view

    def set_robot_state(self, robot_state: RobotState) -> None:
        self.last_scan_state = robot_state
        self.state_log.add_state(robot_state)

    def get_state(self, time: int) -> RobotState | None:
        return self.state_log.get_state(time)

    def get_bot_distance_sq(self, name) -> float:
        return self._bot_distances_sq.get(name, math.nan)

    def set_bot_distance_sq(self, name, distance: float) -> None:
        self._bot_distances_sq[name] = distance

    def remove_distance_sq(self, bot_name) -> None:
        self._bot_distances_sq.pop(bot_name, None)

    def clear_distances_sq(self) -> None:
        self._bot_distances_sq.clear()


class EnemyDataManager:
    WARNING_ROBOT_DEATH_UNKNOWN = "A bot died that I never knew existed!"

    def __init__(self, enemies_total: int, battle_field: BattleField, predictor: MovementPredictor) -> None:
        self._duel_enemy = None
        self.enemies_total = enemies_total
        self.battle_field = battle_field
        self.predictor = predictor
        self._enemies: dict[object, Enemy] = {}

    def has_enemy(self, bot_name) -> bool:
        return bot_name in self._enemies

    def get_enemy_data(self, bot_name):
        return self._enemies.get(bot_name)

    def get_all_enemy_data(self) -> list:
        return list(self._enemies.values())

    def init_round(self) -> None:
        for enemy_data in self._enemies.values():
            enemy_data.init_round()
        self._duel_enemy = None

    def on_robot_death(self, bot_name) -> None:
        enemy_data = self.get_enemy_data(bot_name)
        if enemy_data is None:
            warn(self.get_label(), self.WARNING_ROBOT_DEATH_UNKNOWN)
            return
        enemy_data.alive = False

    def update_bot_distances(self, my_location: Point) -> None:
        if len(self._enemies) <= 1:
            return
        bot_names = list(self._enemies.keys())
        for x in range(len(bot_names)):
            enemy_data1 = self._enemies[bot_names[x]]
            for y in range(x + 1, len(bot_names)):
                enemy_data2 = self._enemies[bot_names[y]]
                if enemy_data1.alive and enemy_data2.alive:
                    distance_sq = enemy_data1.last_scan_state.location.distance_sq(enemy_data2.last_scan_state.location)
                    enemy_data1.set_bot_distance_sq(bot_names[y], distance_sq)
                    enemy_data2.set_bot_distance_sq(bot_names[x], distance_sq)
                else:
                    if not enemy_data1.alive:
                        enemy_data2.remove_distance_sq(bot_names[x])
                    if not enemy_data2.alive:
                        enemy_data1.remove_distance_sq(bot_names[y])
                enemy_data1.distance = my_location.distance(enemy_data1.last_scan_state.location)

    def get_closest_living_bot(self, location: Point):
        closest_enemy = None
        closest_distance = math.inf
        for enemy_data in self._enemies.values():
            if enemy_data.alive:
                this_distance = location.distance_sq(enemy_data.last_scan_state.location)
                if this_distance < closest_distance:
                    closest_enemy = enemy_data
                    closest_distance = this_distance
        return closest_enemy

    def duel_enemy(self):
        return self._duel_enemy

    def is_melee_battle(self) -> bool:
        return self.enemies_total > 1

    def get_label(self) -> str:
        raise NotImplementedError
