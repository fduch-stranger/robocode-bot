"""``lxx.bullets.enemy.EnemyBulletManager``: detects enemy fire, tracks the
predicted bullets, their shadows from our own bullets, and feeds the gun model.
"""
from __future__ import annotations

import math

from tomcat_port.bullets import BulletInfo, BulletShadow, BulletState, EnemyBulletPredictionData, LXXBullet
from tomcat_port.enemy_gun_model import FIRE_DETECTION_LATENCY, AdvancedEnemyGunModel
from tomcat_port.lxx_utils import LXXPoint, bullet_power, bullet_speed, intersection, stop_time
from tomcat_port.waves import Wave, WaveCallback

EMPTY_PREDICTION_DATA = EnemyBulletPredictionData([], 0, {}, None, None)


class EnemyBulletManager(WaveCallback):
    def __init__(self, office, robot) -> None:
        self.office = office
        self.robot = robot
        self.enemy_gun_model = AdvancedEnemyGunModel(office)
        self.wave_manager = office.wave_manager
        self.bullet_manager = office.bullet_manager
        self.turn_snapshots_log = office.turn_snapshots_log
        self._predicted_bullets: dict[Wave, LXXBullet] = {}
        self._listeners: list = []
        self._next_fire_time = 0.0
        self.ghost_bullets_count = 0

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    # TargetManagerListener
    def target_updated(self, target) -> None:
        if not (target.is_fire_last_tick() or (not target.is_alive and target.gun_heat == 0)):
            return
        power = max(0.1, max(0.0, target.expected_energy()) - target.energy)
        speed = bullet_speed(power)
        target_prev = target.prev_snapshot
        robot_prev = self.robot.prev_snapshot
        angle_to_me = target_prev.angle_to(robot_prev)
        fake_bullet = BulletInfo(angle_to_me, power, target_prev.x, target_prev.y)
        wave = self.wave_manager.launch_wave(target_prev, robot_prev, self.robot, speed, self)
        lxx_bullet = LXXBullet(fake_bullet, wave)
        shadows = self._get_bullet_shadows(lxx_bullet, self.bullet_manager.get_bullets())
        self._add_bullet_shadows(lxx_bullet, shadows)
        lxx_bullet.aim_prediction_data = self.enemy_gun_model.get_prediction_data(
            target,
            self.turn_snapshots_log.get_last_snapshot(target, FIRE_DETECTION_LATENCY),
            list(shadows.values()),
        )
        self._predicted_bullets[wave] = lxx_bullet
        for listener in self._listeners:
            listener.bullet_fired(lxx_bullet)

    # WaveCallback
    def wave_passing(self, wave: Wave) -> None:
        lxx_bullet = self._get_lxx_bullet_for_wave(wave)
        for listener in self._listeners:
            listener.bullet_passing(lxx_bullet)

    def wave_broken(self, wave: Wave) -> None:
        lxx_bullet = self._get_lxx_bullet_for_wave(wave)
        if lxx_bullet is not None and lxx_bullet.state is BulletState.ON_AIR:
            lxx_bullet.state = BulletState.MISSED
            for listener in self._listeners:
                listener.bullet_miss(lxx_bullet)
        self._predicted_bullets.pop(wave, None)
        if lxx_bullet is not None:
            self.enemy_gun_model.process_miss(lxx_bullet)
        self._update_bullets_on_air()
        if lxx_bullet is not None:
            self.enemy_gun_model.process_visit(lxx_bullet)

    def _update_bullets_on_air(self) -> None:
        for bullet in list(self._predicted_bullets.values()):
            if bullet.state is BulletState.ON_AIR:
                self.enemy_gun_model.update_bullet_prediction_data(bullet)

    def on_bullet_hit_bullet(self, my_bullet: BulletInfo, hit_bullet: BulletInfo) -> None:
        wave = self._get_wave(hit_bullet)
        if wave is None:
            self.ghost_bullets_count += 1
            return
        lxx_bullet = self._get_lxx_bullet(wave, hit_bullet)
        if lxx_bullet is None:
            return
        lxx_bullet.state = BulletState.INTERCEPTED
        for listener in self._listeners:
            listener.bullet_intercepted(lxx_bullet)
        mine = self.bullet_manager.get_lxx_bullet(my_bullet)
        if mine is not None:
            for enemy_bullet in self.get_all_bullets_on_air():
                shadow = enemy_bullet.get_bullet_shadow(mine)
                if shadow is not None and not shadow.is_passed:
                    enemy_bullet.remove_bullet_shadow(mine)
        self.enemy_gun_model.process_intercept(lxx_bullet)
        self._update_bullets_on_air()

    def on_hit_by_bullet(self, bullet: BulletInfo) -> None:
        wave = self._get_wave(bullet)
        if wave is None:
            self.ghost_bullets_count += 1
            return
        lxx_bullet = self._get_lxx_bullet(wave, bullet)
        if lxx_bullet is None:
            return
        lxx_bullet.state = BulletState.HITTED
        for listener in self._listeners:
            listener.bullet_hit(lxx_bullet)
        self.enemy_gun_model.process_hit(lxx_bullet)
        self._update_bullets_on_air()

    def _get_wave(self, bullet: BulletInfo) -> Wave | None:
        bullet_pos = LXXPoint(bullet.x, bullet.y)
        for wave in self._predicted_bullets:
            if (
                abs(wave.speed - bullet_speed(bullet.power)) < 0.1
                and abs(wave.traveled_distance - (wave.source_state.a_distance(bullet_pos) + bullet.speed)) < wave.speed + 1
            ):
                return wave
        return None

    def _get_lxx_bullet_for_wave(self, wave: Wave) -> LXXBullet | None:
        heading = wave.source_state.angle_to(wave.target_state)
        pos = wave.source_state.project(heading, wave.traveled_distance)
        fake = BulletInfo(heading, bullet_power(wave.speed), pos.x, pos.y)
        return self._get_lxx_bullet(wave, fake)

    def _get_lxx_bullet(self, wave: Wave, bullet: BulletInfo) -> LXXBullet | None:
        lxx_bullet = self._predicted_bullets.get(wave)
        if lxx_bullet is None:
            return None
        lxx_bullet.bullet = bullet
        return lxx_bullet

    def get_bullets_on_air(self, flight_time_limit: float) -> list[LXXBullet]:
        bullets = []
        for bullet in self._predicted_bullets.values():
            flight_time = (bullet.fire_position.a_distance(bullet.target) - bullet.traveled_distance) / bullet.speed
            if flight_time > flight_time_limit and bullet.state is BulletState.ON_AIR:
                bullets.append(bullet)
        bullets.sort(key=lambda bullet: bullet.flight_time(self.robot))
        return bullets

    def get_all_bullets_on_air(self) -> list[LXXBullet]:
        return [bullet for bullet in self._predicted_bullets.values() if bullet.state is BulletState.ON_AIR]

    def on_tick(self) -> None:
        self._check_bullet_shadows()

    def _check_bullet_shadows(self) -> None:
        my_bullets = self.bullet_manager.get_bullets()
        for enemy_bullet in self.get_all_bullets_on_air():
            eb_cur = enemy_bullet.traveled_distance
            eb_fire_pos = enemy_bullet.fire_position
            eb_next = eb_cur + enemy_bullet.speed
            for my_bullet in my_bullets:
                mb_cur_dist = my_bullet.traveled_distance + my_bullet.speed
                mb_fire_pos = my_bullet.fire_position
                cur_pos = mb_fire_pos.project(my_bullet.heading_radians, mb_cur_dist)
                next_pos = mb_fire_pos.project(my_bullet.heading_radians, mb_cur_dist + my_bullet.speed)
                shadow = enemy_bullet.get_bullet_shadow(my_bullet)
                if shadow is None or eb_fire_pos.a_distance(mb_fire_pos) <= mb_cur_dist:
                    continue
                d_cur = eb_fire_pos.a_distance(cur_pos)
                d_next = eb_fire_pos.a_distance(next_pos)
                if (
                    (d_cur > eb_cur and d_next < eb_next)
                    or (d_next > eb_cur and d_cur < eb_next)
                    or (d_cur > eb_next and d_next < eb_next)
                    or (d_cur > eb_cur and d_next < eb_cur)
                ):
                    shadow.is_passed = True

    def create_future_bullet(self, target) -> LXXBullet:
        cooling = self.robot.gun_cooling_rate
        if target.gun_heat > 0:
            self._next_fire_time = self.robot.time + math.ceil(target.gun_heat / cooling)
        ticks_until_fire = round(target.gun_heat / cooling)
        fire_time = int(self.robot.time + ticks_until_fire)
        wave = Wave(target.current_snapshot, self.robot.current_snapshot, self.robot, bullet_speed(target.fire_power), fire_time)
        bullet = BulletInfo(target.angle_to(self.robot), bullet_power(wave.speed), target.x, target.y)
        lxx_bullet = LXXBullet(bullet, wave)
        if ticks_until_fire <= stop_time(self.robot.speed) and self.robot.time <= self._next_fire_time:
            shadows = self._get_bullet_shadows(lxx_bullet, self.bullet_manager.get_bullets())
            self._add_bullet_shadows(lxx_bullet, shadows)
            time_delta = 0 if ticks_until_fire > 0 else 1
            prediction = self.enemy_gun_model.get_prediction_data(
                target, self.turn_snapshots_log.get_last_snapshot(target, time_delta), list(shadows.values())
            )
        else:
            prediction = EMPTY_PREDICTION_DATA
        lxx_bullet.aim_prediction_data = prediction
        return lxx_bullet

    @staticmethod
    def _add_bullet_shadows(lxx_bullet: LXXBullet, shadows: dict) -> None:
        for my_bullet, shadow in shadows.items():
            lxx_bullet.add_bullet_shadow(my_bullet, shadow)

    def _get_bullet_shadows(self, enemy_bullet: LXXBullet, my_bullets: list[LXXBullet]) -> dict:
        my_bullets = list(my_bullets)
        shadows: dict = {}
        eb_fire_pos = enemy_bullet.fire_position
        time_delta = 0
        while my_bullets:
            eb_cur = enemy_bullet.traveled_distance + enemy_bullet.speed * time_delta
            eb_next = eb_cur + enemy_bullet.speed
            to_remove: list[LXXBullet] = []
            for my_bullet in my_bullets:
                mb_cur_dist = my_bullet.traveled_distance + my_bullet.speed * time_delta
                mb_fire_pos = my_bullet.fire_position
                cur_pos = mb_fire_pos.project(my_bullet.heading_radians, mb_cur_dist)
                if not self.robot.battle_field.contains(cur_pos):
                    to_remove.append(my_bullet)
                    continue
                next_pos = mb_fire_pos.project(my_bullet.heading_radians, mb_cur_dist + my_bullet.speed)
                d_cur = eb_fire_pos.a_distance(cur_pos)
                d_next = eb_fire_pos.a_distance(next_pos)
                pnt1 = pnt2 = None
                try:
                    if d_cur < eb_next and d_next > eb_cur:
                        pnt1, pnt2 = cur_pos, next_pos
                        to_remove.append(my_bullet)
                    elif d_next < eb_cur and d_cur > eb_next:
                        pnt1 = intersection(cur_pos, next_pos, eb_fire_pos, eb_cur)[0]
                        pnt2 = intersection(cur_pos, next_pos, eb_fire_pos, eb_next)[0]
                        to_remove.append(my_bullet)
                    elif d_cur > eb_next and d_next < eb_next:
                        pnt1 = next_pos
                        pnt2 = intersection(cur_pos, next_pos, eb_fire_pos, eb_next)[0]
                        to_remove.append(my_bullet)
                    elif d_cur > eb_cur and d_next < eb_cur:
                        pnt1 = intersection(cur_pos, next_pos, eb_fire_pos, eb_cur)[0]
                        pnt2 = cur_pos
                        to_remove.append(my_bullet)
                except IndexError:
                    # The Java code assumes an intersection exists; skip the shadow when it does not.
                    if my_bullet not in to_remove:
                        to_remove.append(my_bullet)
                    continue
                if pnt1 is not None and pnt2 is not None:
                    bo1 = enemy_bullet.bearing_offset_radians(pnt1)
                    bo2 = enemy_bullet.bearing_offset_radians(pnt2)
                    shadows[my_bullet] = BulletShadow(min(bo1, bo2), max(bo1, bo2))
            for my_bullet in to_remove:
                if my_bullet in my_bullets:
                    my_bullets.remove(my_bullet)
            time_delta += 1
            if time_delta > 400:
                break
        return shadows

    def bullet_fired(self, bullet: LXXBullet) -> None:
        for enemy_bullet in self.get_all_bullets_on_air():
            shadows = self._get_bullet_shadows(enemy_bullet, [bullet])
            shadow = shadows.get(bullet)
            if shadow is None:
                continue
            enemy_bullet.add_bullet_shadow(bullet, shadow)
        self._update_bullets_on_air()
