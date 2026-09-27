"""``lxx.office``: wiring of the per-round managers, plus ``StatisticsManager``.

Java routed engine events through a listener bus; here the bot adapter calls
the ``on_*`` methods below, which fan out in the same order the Java
listeners were registered.
"""
from __future__ import annotations

from tomcat_port.bullets import BulletInfo, LXXBullet
from tomcat_port.enemy_bullets import EnemyBulletManager
from tomcat_port.gun import DataViewManager, TomcatEyes
from tomcat_port.lxx_utils import HitRate
from tomcat_port.my_bullets import BulletManager
from tomcat_port.targeting import (
    BulletHitEvent,
    HitByBulletEvent,
    HitRobotEvent,
    RobotDeathEvent,
    ScannedEvent,
    TargetManager,
)
from tomcat_port.ts_log import AttributesManager, TurnSnapshotsLog
from tomcat_port.waves import WaveManager


class BattleStatistics:
    """The Java static hit-rate fields, persisted across rounds."""

    def __init__(self) -> None:
        self.my_hit_rate = HitRate()
        self.enemy_hit_rate = HitRate()
        self.my_raw_hit_rate = HitRate()
        self.enemy_raw_hit_rate = HitRate()
        self.wall_hits = 0
        self.skipped_turns = 0


_BATTLE_STATISTICS = BattleStatistics()


def reset_battle_statistics() -> None:
    global _BATTLE_STATISTICS
    _BATTLE_STATISTICS = BattleStatistics()


class StatisticsManager:
    def __init__(self, office, robot) -> None:
        self.office = office
        self.robot = robot
        self.stats = _BATTLE_STATISTICS
        office.bullet_manager.add_listener(self)
        office.enemy_bullet_manager.add_listener(self)

    @property
    def enemy_hit_rate(self) -> HitRate:
        return self.stats.enemy_hit_rate

    def get_my_raw_hit_rate(self) -> float:
        return self.stats.my_raw_hit_rate.get_hit_rate()

    def _is_mine(self, bullet: LXXBullet) -> bool:
        return bullet.source_state.name == self.robot.name

    def bullet_fired(self, bullet: LXXBullet) -> None:
        return None

    def bullet_hit(self, bullet: LXXBullet) -> None:
        if self._is_mine(bullet):
            self.stats.my_hit_rate.hit()
            self.stats.my_raw_hit_rate.hit()
        else:
            self.stats.enemy_hit_rate.hit()
            self.stats.enemy_raw_hit_rate.hit()

    def bullet_miss(self, bullet: LXXBullet) -> None:
        if self._is_mine(bullet):
            self.stats.my_hit_rate.miss()
            self.stats.my_raw_hit_rate.miss()
        else:
            self.stats.enemy_hit_rate.miss()
            self.stats.enemy_raw_hit_rate.miss()

    def bullet_intercepted(self, bullet: LXXBullet) -> None:
        if self._is_mine(bullet):
            self.stats.my_raw_hit_rate.miss()
        else:
            self.stats.enemy_raw_hit_rate.miss()

    def bullet_passing(self, bullet: LXXBullet) -> None:
        return None

    def on_hit_wall(self) -> None:
        self.stats.wall_hits += 1

    def on_skipped_turn(self) -> None:
        self.stats.skipped_turns += 1


class Office:
    def __init__(self, robot) -> None:
        self.robot = robot
        self.tomcat_eyes = TomcatEyes()
        self.target_manager = TargetManager(robot)
        self.wave_manager = WaveManager()
        self.bullet_manager = BulletManager(self.wave_manager)
        self.attributes_manager = AttributesManager(robot)
        self.turn_snapshots_log = TurnSnapshotsLog(self)
        self.target_manager.add_listener(self.turn_snapshots_log)
        self.enemy_bullet_manager = EnemyBulletManager(self, robot)
        self.target_manager.add_listener(self.enemy_bullet_manager)
        self.statistics_manager = StatisticsManager(self, robot)
        self.data_view_manager = DataViewManager(self.target_manager, self.turn_snapshots_log)

    @property
    def time(self) -> int:
        return self.robot.time

    # Event fan-out in the Java listener order: target manager, wave manager,
    # bullet manager, enemy bullet manager, statistics, data views.
    def on_tick(self) -> None:
        self.target_manager.on_tick()
        self.wave_manager.on_tick()
        self.enemy_bullet_manager.on_tick()
        self.data_view_manager.on_tick()

    def on_fire(self, bullet: LXXBullet) -> None:
        self.bullet_manager.add_bullet(bullet)
        self.enemy_bullet_manager.bullet_fired(bullet)

    def on_scanned(self, name, event: ScannedEvent) -> None:
        self.target_manager.update_target(event, name)

    def on_hit_by_bullet(self, name, bullet: BulletInfo) -> None:
        self.target_manager.update_target(HitByBulletEvent(self.time, bullet.power), name)
        self.enemy_bullet_manager.on_hit_by_bullet(bullet)

    def on_bullet_hit(self, victim_name, bullet: BulletInfo, victim_energy: float) -> None:
        self.target_manager.update_target(BulletHitEvent(self.time, bullet.power, bullet.x, bullet.y, victim_energy), victim_name)
        self.bullet_manager.on_bullet_hit(bullet, victim_name)

    def on_bullet_hit_bullet(self, my_bullet: BulletInfo, hit_bullet: BulletInfo) -> None:
        self.bullet_manager.on_bullet_hit_bullet(my_bullet)
        self.enemy_bullet_manager.on_bullet_hit_bullet(my_bullet, hit_bullet)

    def on_bullet_missed(self, my_bullet: BulletInfo) -> None:
        self.bullet_manager.on_bullet_missed(my_bullet)

    def on_hit_robot(self, name, event: HitRobotEvent) -> None:
        self.target_manager.update_target(event, name)

    def on_robot_death(self, name) -> None:
        self.target_manager.on_target_killed(name)
        self.target_manager.update_target(RobotDeathEvent(self.time), name)
