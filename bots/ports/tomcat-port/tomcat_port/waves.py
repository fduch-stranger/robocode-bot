"""Waves ported from ``lxx.utils.wave``: ``Wave``, ``WaveCallback`` and ``WaveManager``."""
from __future__ import annotations

from tomcat_port.lxx_utils import (
    IntervalDouble,
    normal_relative_angle,
    robot_rect_contains,
    robot_width_in_radians,
)


class Wave:
    def __init__(self, source_state, target_state, target, speed: float, launch_time: int) -> None:
        self.source_state = source_state
        self.target_state = target_state
        self.target = target
        self.launch_time = launch_time
        self.speed = speed
        self.no_bearing_offset = source_state.angle_to(target_state)
        self.is_passed = False
        self.hit_bearing_offset_interval: IntervalDouble | None = None
        self.carried_bullet = None

    @property
    def traveled_distance(self) -> float:
        return (self.target.time - self.launch_time + 1) * self.speed

    def check(self) -> bool:
        target = self.target
        angle_to_target = self.source_state.angle_to(target)
        bullet_pos = self.source_state.project(angle_to_target, self.traveled_distance)
        contains = robot_rect_contains(target, bullet_pos.x, bullet_pos.y)
        if contains:
            self.is_passed = True
            bo = normal_relative_angle(angle_to_target - self.no_bearing_offset)
            target_width = robot_width_in_radians(angle_to_target, self.source_state.a_distance(target))
            current_interval = IntervalDouble(bo - target_width / 2, bo + target_width / 2)
            if self.hit_bearing_offset_interval is None:
                self.hit_bearing_offset_interval = current_interval
            else:
                self.hit_bearing_offset_interval.a = min(self.hit_bearing_offset_interval.a, current_interval.a)
                self.hit_bearing_offset_interval.b = max(self.hit_bearing_offset_interval.b, current_interval.b)
        return contains

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Wave) and self.launch_time == other.launch_time and self.source_state == other.source_state

    def __hash__(self) -> int:
        return hash((self.source_state, self.launch_time))


class WaveCallback:
    def wave_passing(self, wave: Wave) -> None:
        raise NotImplementedError

    def wave_broken(self, wave: Wave) -> None:
        raise NotImplementedError


class WaveManager:
    def __init__(self) -> None:
        self._waves: dict[object, list[Wave]] = {}
        self._wave_callbacks: dict[Wave, list[WaveCallback]] = {}

    def launch_wave(self, source_state, target_state, target, speed: float, callback: WaveCallback | None) -> Wave:
        wave = Wave(source_state, target_state, target, speed, target.time)
        self._waves.setdefault(source_state.name, []).append(wave)
        self.add_callback(callback, wave)
        return wave

    def add_callback(self, callback: WaveCallback | None, wave: Wave) -> None:
        callbacks = self._wave_callbacks.setdefault(wave, [])
        if callback is not None and callback not in callbacks:
            callbacks.append(callback)

    def on_tick(self) -> None:
        for waves in self._waves.values():
            to_remove: list[Wave] = []
            for wave in waves:
                if not wave.target.is_alive:
                    to_remove.append(wave)
                    continue
                callbacks = self._wave_callbacks.get(wave, [])
                if wave.check():
                    for callback in callbacks:
                        callback.wave_passing(wave)
                elif wave.is_passed:
                    to_remove.append(wave)
                    for callback in callbacks:
                        callback.wave_broken(wave)
                    self._wave_callbacks.pop(wave, None)
            for wave in to_remove:
                waves.remove(wave)
