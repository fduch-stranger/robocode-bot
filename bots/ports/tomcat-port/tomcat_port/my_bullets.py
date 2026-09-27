"""``lxx.bullets.my.BulletManager``: tracks our own bullets and their waves."""
from __future__ import annotations

from tomcat_port.bullets import BulletInfo, BulletSnapshot, BulletState, LXXBullet
from tomcat_port.lxx_utils import LXXPoint, is_near, lateral_direction, max_escape_angle
from tomcat_port.waves import Wave, WaveCallback


class BulletManager(WaveCallback):
    def __init__(self, wave_manager) -> None:
        self.wave_manager = wave_manager
        self._old_bullets: list[LXXBullet] = []
        self._bullets: list[LXXBullet] = []
        self._listeners: list = []
        self._bullets_by_waves: dict[Wave, LXXBullet] = {}

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    def add_bullet(self, bullet: LXXBullet) -> None:
        self._bullets.append(bullet)
        self._bullets_by_waves[bullet.wave] = bullet
        self.wave_manager.add_callback(self, bullet.wave)
        for listener in self._listeners:
            listener.bullet_fired(bullet)

    def on_bullet_hit_bullet(self, my_bullet: BulletInfo) -> None:
        bullet = self.get_lxx_bullet(my_bullet)
        if bullet is None:
            return
        self._remove_bullet(bullet)
        bullet.state = BulletState.INTERCEPTED
        for listener in self._listeners:
            listener.bullet_intercepted(bullet)

    def _remove_bullet(self, bullet: LXXBullet) -> None:
        if bullet in self._bullets:
            self._bullets.remove(bullet)
        self._old_bullets.append(bullet)

    def on_bullet_hit(self, my_bullet: BulletInfo, victim_name) -> None:
        bullet = self.get_lxx_bullet(my_bullet)
        if bullet is None:
            return
        if bullet.target.name == victim_name:
            for listener in self._listeners:
                listener.bullet_hit(bullet)
        elif bullet.traveled_distance >= bullet.distance_to_target:
            for listener in self._listeners:
                listener.bullet_miss(bullet)
        bullet.state = BulletState.HITTED
        self._remove_bullet(bullet)

    def on_bullet_missed(self, my_bullet: BulletInfo) -> None:
        bullet = self.get_lxx_bullet(my_bullet)
        if bullet is None:
            return
        if bullet.target is not None and bullet.target.is_alive:
            for listener in self._listeners:
                listener.bullet_miss(bullet)
            bullet.state = BulletState.MISSED
        self._remove_bullet(bullet)

    def get_lxx_bullet(self, info: BulletInfo) -> LXXBullet | None:
        for bullets in (self._bullets, self._old_bullets):
            if info.bullet_id >= 0:
                for bullet in bullets:
                    if bullet.bullet.bullet_id == info.bullet_id:
                        return bullet
            for bullet in bullets:
                if (
                    is_near(info.heading_radians, bullet.bullet.heading_radians)
                    and is_near(info.power, bullet.bullet.power)
                    and LXXPoint(bullet.bullet.x, bullet.bullet.y).a_distance(LXXPoint(info.x, info.y)) < 40
                ):
                    return bullet
        return None

    def get_first_bullet(self) -> LXXBullet | None:
        for bullet in self._bullets:
            if bullet.fire_position.a_distance(bullet.target) > bullet.traveled_distance:
                return bullet
        return None

    def get_bullets(self) -> list[LXXBullet]:
        return list(self._bullets)

    def wave_passing(self, wave: Wave) -> None:
        return None

    def wave_broken(self, wave: Wave) -> None:
        bullet = self._bullets_by_waves.pop(wave, None)
        if bullet is None or wave.hit_bearing_offset_interval is None:
            return
        direction = lateral_direction(wave.source_state, wave.target_state)
        guess_factor = wave.hit_bearing_offset_interval.center() * direction / max_escape_angle(wave.speed)
        bullet.target.add_visit(guess_factor)

    def get_bullet_snapshots(self) -> list[BulletSnapshot]:
        return [
            BulletSnapshot(
                bullet.wave.source_state,
                bullet.wave.target_state,
                bullet.no_bearing_offset,
                bullet.traveled_distance,
                bullet.speed,
                bullet.wave.launch_time,
            )
            for bullet in self._bullets
        ]
