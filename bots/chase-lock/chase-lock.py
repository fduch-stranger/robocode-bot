import math
import os
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BotDeathEvent,
    BulletFiredEvent,
    BulletHitBotEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from bot_core.debug import DebugLogger, FiredBulletTracker
from bot_core.energy import (
    EnemyEnergyCorrectionLedger,
    EnemyFirePowerPrediction,
    EnemyFirePowerPredictor,
    EnergyDropConfig,
    FireGate,
    FireGateConfig,
    GunHeatTracker,
    classify_energy_drop,
)
from bot_core.gun import AimSolution, GunConfig, TargetMotion, VirtualGunSystem, should_log_switch_decision
from bot_core.movement import (
    FlatteningDecision,
    MinimumRiskConfig,
    MinimumRiskMovement,
    MovementCommand,
    MovementFlattener,
)
from bot_core.motion import OwnMotionTracker
from bot_core.radar import RadarLockConfig, lock_radar_to_target
from bot_core.geometry.angles import bearing_to
from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to, drive_to_destination
from bot_core.target_snapshot import TargetSnapshot, interpolate_target, target_from_hit_bot, target_from_scan
from bot_core.telemetry.energy import EnergyTelemetry
from bot_core.telemetry.fire import FireTelemetry, FireTick
from bot_core.telemetry.movement import MovementTelemetry
from bot_core.telemetry.targeting import TargetingTelemetry


FIRE_ALIGNMENT_DEGREES = 7
CHASE_SELECTABLE_GUN_MODES = frozenset({"linear", "traditional_gf", "dynamic_cluster"})
CHASE_FORCE_GUN_MODES = CHASE_SELECTABLE_GUN_MODES | frozenset({"displacement"})


def _forced_gun_mode() -> str | None:
    mode = os.environ.get("ROBOCODE_CHASE_GUN_MODE", "").strip()
    return mode if mode in CHASE_FORCE_GUN_MODES else None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class GunPolicy:
    selectable_modes: frozenset[str] = CHASE_SELECTABLE_GUN_MODES
    forced_mode: str | None = _forced_gun_mode()
    eval_waves_enabled: bool = _env_flag("ROBOCODE_CHASE_GUN_EVAL")
    eval_wave_min_interval: int = _env_int("ROBOCODE_CHASE_GUN_EVAL_INTERVAL", 8)
    knn_min_samples: int = 60
    min_visits: int = 90
    switch_margin: float = 0.08
    min_switch_score: float = 0.30
    traditional_gf_min_switch_visits: int = 120
    traditional_gf_min_switch_score: float = 0.30
    switch_diagnostics_interval: int = 30


GUN_POLICY = GunPolicy()
TARGET_MEMORY_TURNS = 24
FIRE_MEMORY_TURNS = 1
REACQUIRE_TARGET_TURNS = 4
DROP_LOST_TARGET_TURNS = 9
PREFERRED_MIN_DISTANCE = 320
PREFERRED_MAX_DISTANCE = 470
MELEE_PRESSURE_MIN_DISTANCE = 260
MELEE_PRESSURE_MAX_DISTANCE = 430
MELEE_FINISH_TARGET_ENERGY = 28
PANIC_RETREAT_DISTANCE = 160
MELEE_PANIC_RETREAT_DISTANCE = 180
CLOSE_RESET_DISTANCE = 285
MELEE_CLOSE_RESET_DISTANCE = 240
FINISH_TARGET_ENERGY = 18
FINISH_DISTANCE = 240
ENEMY_FIRE_MIN_DROP = 0.1
ENEMY_FIRE_MAX_DROP = 3.0
ENEMY_FIRE_SCAN_GAP_TURNS = 4
ENEMY_FIRE_CLOSE_COLLISION_DISTANCE = 75
ENEMY_FIRE_CLOSE_COLLISION_MAX_DROP = 0.8
ENEMY_FIRE_ACTIVE_EVASION_MIN_DISTANCE = 220
MELEE_FIRE_ACTIVE_EVASION_MIN_DISTANCE = 120
GUN_HEAT_WAVES_ACTIVE = True
GUN_HEAT_WAVE_MIN_DISTANCE = 220
GUN_HEAT_WAVE_MAX_TARGET_AGE = 2
RADAR_LOCK_RATE = 24
RADAR_SEARCH_RATE = 18
RADAR_REACQUIRE_RATE = 24
RADAR_LOST_SWEEP_RATE = 24
GUN_SEARCH_RATE = 18
RADAR_REACQUIRE_MIN_ERROR = 8
RADAR_REACQUIRE_OVERSHOOT = 8
RADAR_REACQUIRE_WIDEN_PER_TURN = 2
RADAR_REACQUIRE_MAX_OVERSHOOT = 42
RADAR_LOCK_OVERSCAN = 12
RADAR_VISIBLE_REACQUIRE_OVERSCAN = 18
CURRENT_TARGET_BONUS = 80
RECENT_THREAT_BONUS = 120
MELEE_CURRENT_TARGET_BONUS = 28
MELEE_RECENT_THREAT_BONUS = 48
THREAT_MEMORY_TURNS = 35
FIELD_MARGIN = 18
WALL_MARGIN = 90
WALL_LOOKAHEAD_TICKS = 11
WALL_ESCAPE_SPEED = 6
APPROACH_STRAFE_OFFSET = 68
ORBIT_STRAFE_OFFSET = 92
EVADE_STRAFE_OFFSET = 102
RETREAT_STRAFE_OFFSET = 124
EVADE_TURNS = 36
FLATTENER_ACTIVE = True
RADAR_CONFIG = RadarLockConfig(
    search_rate=RADAR_SEARCH_RATE,
    lock_rate=RADAR_LOCK_RATE,
    reacquire_rate=RADAR_REACQUIRE_RATE,
    reacquire_min_error=RADAR_REACQUIRE_MIN_ERROR,
    lock_overscan=RADAR_LOCK_OVERSCAN,
    reacquire_overscan=RADAR_VISIBLE_REACQUIRE_OVERSCAN,
)
ENERGY_DROP_CONFIG = EnergyDropConfig(
    min_fire_power=ENEMY_FIRE_MIN_DROP,
    max_fire_power=ENEMY_FIRE_MAX_DROP,
    max_scan_gap=ENEMY_FIRE_SCAN_GAP_TURNS,
    close_collision_distance=ENEMY_FIRE_CLOSE_COLLISION_DISTANCE,
    close_collision_max_drop=ENEMY_FIRE_CLOSE_COLLISION_MAX_DROP,
)
FIRE_GATE = FireGate(
    FireGateConfig(
        fire_memory_turns=FIRE_MEMORY_TURNS,
        alignment_degrees=FIRE_ALIGNMENT_DEGREES,
        energy_margin=5,
    )
)


class ChaseLock(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Chase Lock",
                version="1.0",
                authors=["robocode-bot"],
                description="Target-lock pressure bot with virtual-gun aiming, enemy-fire prediction, expected gun-heat waves, and wave-informed evasion.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._targets: dict[int, TargetSnapshot] = {}
        self._target_id: int | None = None
        self._recent_threat_id: int | None = None
        self._recent_threat_turn = -1000
        self._evade_direction = 1
        self._evade_until_turn = -1
        self._radar_sweep_direction = 1
        self._last_turn_number = -1
        self._last_enemy_fire_turn = -1000
        self._enemy_energy_corrections = EnemyEnergyCorrectionLedger()
        self._target_accel: dict[int, float] = {}
        self._last_velocity_change_turn: dict[int, int] = {}
        self._melee_round = False
        self._enemy_gun_heat = GunHeatTracker()
        self._enemy_fire_power = EnemyFirePowerPredictor()
        self._last_enemy_power_prediction: dict[int, EnemyFirePowerPrediction] = {}
        self._gun = VirtualGunSystem(
            GunConfig(
                selectable_modes=GUN_POLICY.selectable_modes,
                forced_mode=GUN_POLICY.forced_mode,
                eval_waves_enabled=GUN_POLICY.eval_waves_enabled,
                eval_wave_min_interval=GUN_POLICY.eval_wave_min_interval,
                knn_min_samples=GUN_POLICY.knn_min_samples,
                min_visits=GUN_POLICY.min_visits,
                switch_margin=GUN_POLICY.switch_margin,
                min_switch_score=GUN_POLICY.min_switch_score,
                traditional_gf_min_switch_visits=GUN_POLICY.traditional_gf_min_switch_visits,
                traditional_gf_min_switch_score=GUN_POLICY.traditional_gf_min_switch_score,
            )
        )
        self._movement = MovementFlattener()
        self._own_motion = OwnMotionTracker()
        self._minimum_risk = MinimumRiskMovement(
            MinimumRiskConfig(
                candidate_distances=(180.0, 260.0, 340.0, 430.0),
                field_margin=96.0,
                preferred_target_distance=430.0,
                max_target_distance=720.0,
                close_enemy_distance=270.0,
                travel_weight=0.001,
                enemy_weight=31000.0,
                close_enemy_weight=42.0,
                target_distance_weight=0.00032,
                threat_lateral_weight=2.6,
                threat_distance_weight=14000.0,
                destination_commit_ticks=8,
                destination_switch_risk_ratio=0.9,
            )
        )
        self._debug = DebugLogger(self, "chase-lock")
        self._energy_telemetry = EnergyTelemetry(self._debug)
        self._fire_telemetry = FireTelemetry(self._debug)
        self._movement_telemetry = MovementTelemetry(self._debug)
        self._targeting_telemetry = TargetingTelemetry(self._debug)
        self._fired_bullets = FiredBulletTracker()
        self._last_gun_decision_log_turn: dict[int, int] = {}

    def run(self) -> None:
        self.body_color = Color.from_rgb(70, 170, 105)
        self.turret_color = Color.from_rgb(26, 105, 62)
        self.radar_color = Color.from_rgb(185, 255, 205)
        self.bullet_color = Color.from_rgb(110, 255, 145)
        self.scan_color = Color.from_rgb(165, 255, 200)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.max_speed = 8

        while self.running:
            self._own_motion.update(self)
            self._track_or_search()
            self.go()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        self._reset_if_new_round()
        previous = self._targets.get(event.scanned_bot_id)
        previous_age = self.turn_number - previous.seen_turn if previous is not None else None
        if previous is not None:
            self._update_target_motion_stats(event, previous)
            fire_detected = self._detect_enemy_fire(event, previous, previous_age or 0)
        else:
            self._consume_enemy_energy_correction(event.scanned_bot_id, self.turn_number, -1)
            fire_detected = False
        self._targets[event.scanned_bot_id] = target_from_scan(event, self.turn_number)
        if len(self._targets) > 1:
            self._melee_round = True
        target = self._targets[event.scanned_bot_id]
        self._gun.observe_target(target)
        self._log_wave_visits(target)
        if not fire_detected:
            self._record_gun_heat_wave(target)
        if previous is None:
            self._targeting_telemetry.record_scan_new(event.scanned_bot_id, event.energy, event.x, event.y)
        elif previous_age is not None and previous_age > REACQUIRE_TARGET_TURNS:
            self._targeting_telemetry.record_scan_reacquired(event.scanned_bot_id, previous_age, previous, event.x, event.y)

    def _update_target_motion_stats(self, event: ScannedBotEvent, previous: TargetSnapshot) -> None:
        speed_delta = event.speed - previous.speed
        self._target_accel[event.scanned_bot_id] = speed_delta
        direction_delta = abs(((event.direction - previous.direction + 180) % 360) - 180)
        if abs(speed_delta) > 0.35 or direction_delta > 7:
            self._last_velocity_change_turn[event.scanned_bot_id] = self.turn_number

    def _detect_enemy_fire(self, event: ScannedBotEvent, previous: TargetSnapshot, scan_gap: int) -> bool:
        distance = distance_to(self, event.x, event.y)
        energy_correction = self._consume_enemy_energy_correction(
            event.scanned_bot_id,
            self.turn_number,
            previous.seen_turn,
        )
        signal = classify_energy_drop(
            previous.energy,
            event.energy,
            scan_gap,
            distance,
            ENERGY_DROP_CONFIG,
            energy_correction=energy_correction,
        )
        heat_state = self._enemy_gun_heat.update(event.scanned_bot_id, self.turn_number, self.gun_cooling_rate)
        if not signal.is_fire:
            if signal.raw_energy_drop > 0 or signal.energy_correction:
                self._energy_telemetry.record_drop_ignored(
                    event.scanned_bot_id,
                    signal,
                    scan_gap,
                    distance,
                    previous.energy,
                    event.energy,
                )
            return False

        self._recent_threat_id = event.scanned_bot_id
        self._recent_threat_turn = self.turn_number
        self._last_enemy_fire_turn = self.turn_number
        previous_prediction = self._last_enemy_power_prediction.pop(event.scanned_bot_id, None)
        self._enemy_fire_power.record(
            event.scanned_bot_id,
            enemy_energy=previous.energy,
            our_energy=self.energy,
            distance=distance,
            fire_power=signal.fire_power or 1.5,
            previous_prediction=previous_prediction,
        )
        heat_state = self._enemy_gun_heat.record_fire(
            event.scanned_bot_id,
            self.turn_number,
            signal.fire_power or 1.5,
            self.gun_cooling_rate,
        )
        current_target = target_from_scan(event, self.turn_number)
        estimated_fire_turn = max(previous.seen_turn + 1, self.turn_number - max(0, scan_gap - 1))
        fire_source = interpolate_target(previous, current_target, estimated_fire_turn)
        movement_wave = self._movement.record_enemy_fire(
            self,
            fire_source,
            signal.fire_power or 1.5,
            fired_turn=estimated_fire_turn,
            **self._own_motion.movement_wave_kwargs(self.turn_number),
        )
        melee_active = self._melee_round or self.enemy_count > 1 or len(self._targets) > 1
        active_evasion = (
            distance >= ENEMY_FIRE_ACTIVE_EVASION_MIN_DISTANCE
            if not melee_active
            else distance >= MELEE_FIRE_ACTIVE_EVASION_MIN_DISTANCE
        )
        if active_evasion:
            if melee_active and not self._wall_risk(8):
                self._evade_direction *= -1
            self._evade_until_turn = max(self._evade_until_turn, self.turn_number + signal.evade_ticks)
        power_mae = self._enemy_fire_power.mean_absolute_error(event.scanned_bot_id)
        self._energy_telemetry.record_enemy_fire_detected(
            event.scanned_bot_id,
            signal,
            scan_gap,
            distance,
            ("active_melee" if melee_active else "active_duel") if active_evasion else "threat_only",
            self._evade_until_turn,
            movement_wave is not None,
            previous_prediction,
            self._enemy_fire_power.sample_count(event.scanned_bot_id),
            power_mae,
            previous_energy=previous.energy,
            energy=event.energy,
            evade_direction=self._evade_direction,
            known_targets=len(self._targets),
            heat_state=heat_state,
        )
        return True

    def _record_gun_heat_wave(self, target: TargetSnapshot) -> None:
        if not GUN_HEAT_WAVES_ACTIVE:
            return
        age = self.turn_number - target.seen_turn
        distance = distance_to(self, target.x, target.y)
        if len(self._targets) > 1 or age > GUN_HEAT_WAVE_MAX_TARGET_AGE or distance < GUN_HEAT_WAVE_MIN_DISTANCE:
            self._enemy_gun_heat.update(target.bot_id, self.turn_number, self.gun_cooling_rate)
            return

        prediction = self._enemy_fire_power.predict(
            target.bot_id,
            enemy_energy=target.energy,
            our_energy=self.energy,
            distance=distance,
        )
        fire_power = self._enemy_gun_heat.expected_fire_power(
            target.bot_id,
            self.turn_number,
            self.gun_cooling_rate,
            predicted_fire_power=prediction.fire_power,
        )
        if fire_power is None:
            return

        self._last_enemy_power_prediction[target.bot_id] = prediction
        movement_wave = self._movement.record_enemy_fire(
            self,
            target,
            fire_power,
            wave_kind="expected",
            expected_confidence=prediction.confidence,
            **self._own_motion.movement_wave_kwargs(self.turn_number),
        )
        self._energy_telemetry.record_gun_heat_wave(target.bot_id, fire_power, prediction, distance, age, movement_wave is not None)

    def _track_or_search(self) -> None:
        self._reset_if_new_round()
        self._forget_stale_targets()
        self._log_movement_profile_visits()
        target = self._select_target()
        if target is None:
            self._search()
            self._targeting_telemetry.sample_search(known_targets=0)
            return

        distance = distance_to(self, target.x, target.y)
        body_bearing = bearing_to(self, target.x, target.y, self.direction)
        radar_bearing = bearing_to(self, target.x, target.y, self.radar_direction)
        firepower = self._select_firepower(target, distance)
        use_segmented_gun_stats = self.enemy_count <= 1
        aim = self._gun.aim(
            self,
            target,
            distance,
            firepower,
            self._target_motion(target),
            FIELD_MARGIN,
            allow_traditional_gf=use_segmented_gun_stats,
            allow_segmented_stats=use_segmented_gun_stats,
        )
        score_segment = aim.segment_key if use_segmented_gun_stats else None
        if aim.mode_changed:
            self._fire_telemetry.record_gun_switch(target.bot_id, aim, self._gun.score_summary(target.bot_id, score_segment))
        self._maybe_log_gun_switch_decision(target.bot_id, aim)
        age = self.turn_number - target.seen_turn

        if age > REACQUIRE_TARGET_TURNS:
            if age > DROP_LOST_TARGET_TURNS:
                self._drop_lost_target(target, age, distance)
                return

            radar_turn, radar_mode = self._set_lost_target_radar(radar_bearing, age)
            self._set_gun_for_search()
            self._set_search_movement()
            self._targeting_telemetry.sample_reacquire(
                target,
                age=age,
                distance=distance,
                radar_bearing=radar_bearing,
                radar_direction=self.radar_direction,
                radar_turn=radar_turn,
                radar_mode=radar_mode,
                radar_sweep=self._radar_sweep_direction,
                x=self.x,
                y=self.y,
                known_targets=len(self._targets),
            )
            return

        radar_command = lock_radar_to_target(self, target, RADAR_CONFIG)
        if abs(radar_command.turn) >= 1:
            self._radar_sweep_direction = 1 if radar_command.turn > 0 else -1
        self.set_turn_gun_left(aim.gun_bearing)

        movement_mode = "wall"
        strafe_offset = None
        flattening = None
        if self._near_wall() or self._wall_risk(8):
            center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
            self.target_speed = WALL_ESCAPE_SPEED
            self.set_turn_left(clamp(center_bearing, -35, 35))
            self._movement_telemetry.sample_target_wall_avoid(self.x, self.y, center_bearing, target.bot_id)
        else:
            movement_mode, strafe_offset, flattening = self._set_chase_movement(target, distance, body_bearing)

        fire_decision = FIRE_GATE.decide(age, distance, aim.gun_bearing, firepower, self.energy)
        if GUN_POLICY.eval_waves_enabled and age <= 2 and self.gun_heat <= 0 and self.energy > firepower:
            self._gun.maybe_add_eval_wave(self, target, firepower, aim)
        self._fire_telemetry.sample_track(
            FireTick(
                target=target,
                age=age,
                distance=distance,
                aim=aim,
                radar=radar_command,
                decision=fire_decision,
                gun_samples=self._gun.sample_count,
                gun_scores=self._gun.score_summary(target.bot_id, score_segment),
                evade_direction=self._evade_direction,
                evading=self.turn_number <= self._evade_until_turn,
                movement_mode=movement_mode,
                strafe_offset=strafe_offset,
                flattening=flattening,
                last_enemy_fire_age=self.turn_number - self._last_enemy_fire_turn,
                known_targets=len(self._targets),
            )
        )
        if fire_decision.can_fire:
            self._gun.set_pending_wave(self._gun.make_wave(self, target, firepower, aim))
            self.set_fire(firepower)

    def _set_chase_movement(
        self,
        target: TargetSnapshot,
        distance: float,
        body_bearing: float,
    ) -> tuple[str, float, FlatteningDecision | None]:
        evading = self.turn_number <= self._evade_until_turn
        panic_distance = PANIC_RETREAT_DISTANCE if len(self._targets) <= 1 else MELEE_PANIC_RETREAT_DISTANCE
        if distance < panic_distance:
            self.target_speed = -7
            self.set_turn_left(body_bearing + RETREAT_STRAFE_OFFSET * self._evade_direction)
            return "panic_retreat", RETREAT_STRAFE_OFFSET, None

        if self._melee_round and len(self._targets) > 1:
            threat_target = self._active_fire_threat() if evading else None
            decision = self._minimum_risk.choose(
                self,
                list(self._targets.values()),
                target,
                threat_target=threat_target,
                dodge_direction=self._evade_direction if threat_target is not None else 0,
            )
            if decision is not None:
                turn, speed = self._drive_to_destination(decision.x, decision.y, 8)
                command = MovementCommand("melee_minimum_risk", turn, speed)
                command.apply(self)
                self._movement_telemetry.sample_minimum_risk(
                    target.bot_id,
                    decision,
                    command,
                    len(self._targets),
                    fire_threat_id=threat_target.bot_id if threat_target is not None else None,
                    include_fire_threat=True,
                )
                return "melee_minimum_risk", 0.0, None

        movement_mode, strafe_offset, move_speed = self._movement_command(target, distance, evading)
        flattening = self._movement.choose_direction(
            self,
            body_bearing,
            strafe_offset,
            move_speed,
            FIELD_MARGIN,
            target.bot_id,
            distance,
            self._evade_direction,
            self.turn_number,
            allow_switch=len(self._targets) <= 1,
            use_surfing=not self._melee_round,
        )
        if flattening.changed:
            if FLATTENER_ACTIVE:
                self._movement_telemetry.record_flattening(target.bot_id, flattening, distance, current_direction=self._evade_direction)
            else:
                self._movement_telemetry.record_flattening_shadow(target.bot_id, flattening, distance, self._evade_direction)
            if FLATTENER_ACTIVE:
                self._evade_direction = flattening.direction

        self.target_speed = move_speed
        self.set_turn_left(body_bearing + strafe_offset * self._evade_direction)
        return movement_mode, strafe_offset, flattening

    def _movement_command(self, target: TargetSnapshot, distance: float, evading: bool) -> tuple[str, float, float]:
        if self._melee_round and self.enemy_count > 1:
            return self._melee_movement_command(target, distance, evading)

        if target.energy <= FINISH_TARGET_ENERGY and distance > FINISH_DISTANCE:
            return "finish_close", APPROACH_STRAFE_OFFSET, 8

        if distance < CLOSE_RESET_DISTANCE:
            return "reset_range", RETREAT_STRAFE_OFFSET, 7

        if distance < PREFERRED_MIN_DISTANCE:
            return "open_range", RETREAT_STRAFE_OFFSET, 7

        if distance > PREFERRED_MAX_DISTANCE:
            return "approach_orbit", APPROACH_STRAFE_OFFSET, 8

        if evading:
            return "evade_orbit", EVADE_STRAFE_OFFSET, 7

        return "mid_orbit", ORBIT_STRAFE_OFFSET, 7

    @staticmethod
    def _melee_movement_command(
        target: TargetSnapshot,
        distance: float,
        evading: bool,
    ) -> tuple[str, float, float]:
        if target.energy <= MELEE_FINISH_TARGET_ENERGY and distance > FINISH_DISTANCE:
            return "melee_finish_close", APPROACH_STRAFE_OFFSET, 8

        if distance < MELEE_CLOSE_RESET_DISTANCE:
            return "melee_reset_range", RETREAT_STRAFE_OFFSET, 7

        if distance > MELEE_PRESSURE_MAX_DISTANCE:
            return "melee_pressure_close", APPROACH_STRAFE_OFFSET, 8

        if distance < MELEE_PRESSURE_MIN_DISTANCE:
            return "melee_open_range", ORBIT_STRAFE_OFFSET, 7

        if evading:
            return "melee_evade_pressure", EVADE_STRAFE_OFFSET, 7

        return "melee_pressure_orbit", APPROACH_STRAFE_OFFSET, 8

    def _select_firepower(self, target: TargetSnapshot, distance: float) -> float:
        if self._melee_round and self.enemy_count > 1:
            return self._select_melee_firepower(target, distance)

        if self.energy <= 18:
            return 0.8 if distance < 260 else 0.6
        if target.energy <= FINISH_TARGET_ENERGY and distance < 320:
            return min(2.2, max(0.6, target.energy / 3.5 + 0.2))

        gun_score, gun_visits = self._gun.active_target_confidence(target.bot_id)
        if distance < 160:
            return 2.2 if self.energy > 36 else 1.6
        if distance < 280 and gun_visits >= 80 and gun_score >= 0.36 and self.energy > 30:
            return 1.8
        if distance < 420 and gun_visits >= 120 and gun_score >= 0.42 and self.energy > 38:
            return 1.6
        if distance < 420:
            return 1.1
        return 0.8

    def _select_melee_firepower(self, target: TargetSnapshot, distance: float) -> float:
        if self.energy <= 16:
            return 0.8 if distance < 220 else 0.6
        if target.energy <= MELEE_FINISH_TARGET_ENERGY and distance < 260:
            return min(2.2, max(0.8, target.energy / 3.2 + 0.2))

        gun_score, gun_visits = self._gun.active_target_confidence(target.bot_id)
        if distance < 160:
            return 2.0
        if distance < 300 and gun_visits >= 70 and gun_score >= 0.36 and self.energy > 28:
            return 1.6
        if distance < 360:
            return 1.2
        return 0.8

    def _target_motion(self, target: TargetSnapshot) -> TargetMotion:
        return TargetMotion(
            acceleration=self._target_accel.get(target.bot_id, 0.0),
            velocity_change_age=self.turn_number - self._last_velocity_change_turn.get(target.bot_id, self.turn_number),
        )

    def _log_wave_visits(self, target: TargetSnapshot) -> None:
        for visit in self._gun.update_waves(self, target):
            self._fire_telemetry.record_wave_visit(visit)
        for visit in self._gun.update_eval_waves(self, target):
            self._fire_telemetry.record_eval_wave_visit(visit)

    def _log_movement_profile_visits(self) -> None:
        for visit in self._movement.update(self):
            self._movement_telemetry.record_profile_visit(visit)

    def _set_lost_target_radar(self, radar_bearing: float, age: int) -> tuple[float, str]:
        if abs(radar_bearing) > RADAR_REACQUIRE_MIN_ERROR:
            overshoot = min(
                RADAR_REACQUIRE_MAX_OVERSHOOT,
                RADAR_REACQUIRE_OVERSHOOT + age * RADAR_REACQUIRE_WIDEN_PER_TURN,
            )
            direction = 1 if radar_bearing > 0 else -1
            radar_turn = clamp(
                radar_bearing + overshoot * direction,
                -RADAR_LOST_SWEEP_RATE,
                RADAR_LOST_SWEEP_RATE,
            )
            self._radar_sweep_direction = direction
            self.set_turn_radar_left(radar_turn)
            return radar_turn, "cached_bearing"

        radar_turn = RADAR_LOST_SWEEP_RATE * self._radar_sweep_direction
        self.set_turn_radar_left(radar_turn)
        return radar_turn, "widen"

    def _reset_if_new_round(self) -> None:
        if self._last_turn_number >= 0 and self.turn_number < self._last_turn_number:
            self._targets.clear()
            self._target_id = None
            self._recent_threat_id = None
            self._recent_threat_turn = -1000
            self._evade_until_turn = -1
            self._last_enemy_fire_turn = -1000
            self._enemy_energy_corrections.clear()
            self._last_enemy_power_prediction.clear()
            self._gun.clear_round_state()
            self._movement.clear_round_state()
            self._minimum_risk.clear_round_state()
            self._enemy_gun_heat.clear_round_state()
            self._fired_bullets.clear()
            self._last_gun_decision_log_turn.clear()
            self._target_accel.clear()
            self._last_velocity_change_turn.clear()
            self._own_motion.reset(self.turn_number)
            self._melee_round = False
            self._log(
                "round.reset",
                previous_turn=self._last_turn_number,
                current_turn=self.turn_number,
            )
        self._last_turn_number = self.turn_number

    def _maybe_log_gun_switch_decision(self, target_id: int, aim: AimSolution) -> None:
        last_turn = self._last_gun_decision_log_turn.get(target_id, -100000)
        if not should_log_switch_decision(aim, self.turn_number, last_turn, GUN_POLICY.switch_diagnostics_interval):
            return
        self._fire_telemetry.record_gun_switch_decision(target_id, aim)
        self._last_gun_decision_log_turn[target_id] = self.turn_number

    def _drop_lost_target(self, target: TargetSnapshot, age: int, distance: float) -> None:
        self._targets.pop(target.bot_id, None)
        self._gun.remove_target(target.bot_id)
        self._movement.remove_target(target.bot_id, clear_profile=False)
        self._enemy_gun_heat.remove_target(target.bot_id)
        self._last_enemy_power_prediction.pop(target.bot_id, None)
        if self._target_id == target.bot_id:
            self._target_id = None
        self._search()
        self._targeting_telemetry.record_target_drop_lost(target, age, distance, len(self._targets))

    def _forget_stale_targets(self) -> None:
        stale_ids = [
            bot_id
            for bot_id, target in self._targets.items()
            if self.turn_number - target.seen_turn > TARGET_MEMORY_TURNS
        ]
        for bot_id in stale_ids:
            self._log("target.stale", bot_id=bot_id)
            del self._targets[bot_id]
            self._gun.remove_target(bot_id)
            self._movement.remove_target(bot_id, clear_profile=False)
            self._enemy_gun_heat.remove_target(bot_id)
            self._last_enemy_power_prediction.pop(bot_id, None)
        if self._target_id not in self._targets:
            self._target_id = None

    def _select_target(self) -> TargetSnapshot | None:
        if not self._targets:
            self._target_id = None
            return None

        previous_id = self._target_id
        fresh_targets = [
            target
            for target in self._targets.values()
            if self.turn_number - target.seen_turn <= REACQUIRE_TARGET_TURNS
        ]
        candidates = fresh_targets if fresh_targets else list(self._targets.values())
        target = min(candidates, key=self._target_score)
        self._target_id = target.bot_id
        if previous_id != target.bot_id:
            self._log(
                "target.select",
                previous=previous_id,
                selected=target.bot_id,
                score=round(self._target_score(target), 1),
                fresh_candidates=len(fresh_targets),
                known_targets=len(self._targets),
            )
        return target

    def _target_score(self, target: TargetSnapshot) -> float:
        distance = distance_to(self, target.x, target.y)
        age = self.turn_number - target.seen_turn
        threat_is_fresh = (
            target.bot_id == self._recent_threat_id
            and self.turn_number - self._recent_threat_turn <= THREAT_MEMORY_TURNS
        )
        if self._melee_round and self.enemy_count > 1:
            current_bonus = MELEE_CURRENT_TARGET_BONUS if target.bot_id == self._target_id else 0
            recent_threat_bonus = MELEE_RECENT_THREAT_BONUS if threat_is_fresh else 0
            return distance * 0.45 + target.energy * 2.0 + age * 92 - current_bonus - recent_threat_bonus

        current_bonus = CURRENT_TARGET_BONUS if target.bot_id == self._target_id else 0
        recent_threat_bonus = RECENT_THREAT_BONUS if threat_is_fresh else 0
        return distance * 0.7 + target.energy * 2.5 + age * 60 - current_bonus - recent_threat_bonus

    def _active_fire_threat(self) -> TargetSnapshot | None:
        if self._recent_threat_id is None:
            return None
        if self.turn_number - self._recent_threat_turn > THREAT_MEMORY_TURNS:
            return None
        return self._targets.get(self._recent_threat_id)

    def _record_enemy_energy_correction(self, target_id: int, correction: float, reason: str) -> None:
        self._enemy_energy_corrections.record(target_id, self.turn_number, correction, reason)

    def _consume_enemy_energy_correction(self, target_id: int, current_turn: int, after_turn: int) -> float:
        return self._enemy_energy_corrections.consume(target_id, current_turn, after_turn, include_after_turn=True)

    def _search(self) -> None:
        self._set_search_movement()
        self._set_gun_for_search()
        self.radar_turn_rate = RADAR_SEARCH_RATE

    def _drive_to_destination(self, x: float, y: float, speed: float) -> tuple[float, float]:
        return drive_to_destination(self, x, y, speed)

    def _set_gun_for_search(self) -> None:
        gun_to_radar = ((self.radar_direction - self.gun_direction + 180) % 360) - 180
        if abs(gun_to_radar) > 5:
            self.set_turn_gun_left(clamp(gun_to_radar, -GUN_SEARCH_RATE, GUN_SEARCH_RATE))
        else:
            self.gun_turn_rate = GUN_SEARCH_RATE * self._radar_sweep_direction

    def _set_search_movement(self) -> None:
        if self._near_wall() or self._wall_risk(6):
            center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
            self.target_speed = WALL_ESCAPE_SPEED
            self.set_turn_left(clamp(center_bearing, -35, 35))
            self._movement_telemetry.sample_search_wall_avoid(self.x, self.y, center_bearing, self._evade_direction, self._near_wall())
            return

        self.target_speed = 4 * self._evade_direction
        self.turn_rate = 3 * self._evade_direction

    def _wall_risk(self, speed: float) -> bool:
        heading = math.radians(self.direction)
        projected_x = self.x + math.cos(heading) * speed * WALL_LOOKAHEAD_TICKS
        projected_y = self.y + math.sin(heading) * speed * WALL_LOOKAHEAD_TICKS
        return (
            projected_x < WALL_MARGIN
            or projected_x > self.arena_width - WALL_MARGIN
            or projected_y < WALL_MARGIN
            or projected_y > self.arena_height - WALL_MARGIN
        )

    def _near_wall(self) -> bool:
        return (
            self.x < WALL_MARGIN
            or self.x > self.arena_width - WALL_MARGIN
            or self.y < WALL_MARGIN
            or self.y > self.arena_height - WALL_MARGIN
        )

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + EVADE_TURNS
        center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
        self.target_speed = WALL_ESCAPE_SPEED
        self.set_turn_left(clamp(center_bearing, -35, 35))
        self._log("hit.wall", evade_direction=self._evade_direction, center_bearing=round(center_bearing, 2))

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._wall_risk(8):
            self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + EVADE_TURNS
        movement_visit = None
        if not self._melee_round:
            movement_visit = self._movement.record_bullet_hit(
                self,
                event.bullet.owner_id,
                event.bullet.power,
            )
        if event.bullet.owner_id in self._targets:
            self._recent_threat_id = event.bullet.owner_id
            self._recent_threat_turn = self.turn_number
            self._target_id = event.bullet.owner_id
        self._log(
            "hit.bullet",
            owner=event.bullet.owner_id,
            power=round(event.bullet.power, 2),
            bullet_direction=round(event.bullet.direction, 1),
            damage=round(event.damage, 2),
            energy=round(event.energy, 1),
            wall_risk=self._wall_risk(8),
            evade_direction=self._evade_direction,
            evade_until=self._evade_until_turn,
            movement_wave_match=movement_visit is not None,
            movement_guess_factor=round(movement_visit.guess_factor, 3) if movement_visit is not None else None,
            movement_bin=movement_visit.bin_index if movement_visit is not None else None,
        )

    def on_bullet_hit(self, event: BulletHitBotEvent) -> None:
        self._record_enemy_energy_correction(event.victim_id, event.damage, "our_bullet_damage")
        bullet_fields = self._fired_bullets.fields_for(event.bullet.bullet_id)
        self._fire_telemetry.record_bullet_hit_bot(
            event.victim_id,
            event.bullet.bullet_id,
            event.bullet.power,
            event.damage,
            event.energy,
            bullet_fields,
        )

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._targets[event.victim_id] = target_from_hit_bot(
            event,
            self.turn_number,
            self._targets.get(event.victim_id),
        )
        self._target_id = event.victim_id
        self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + EVADE_TURNS
        self.target_speed = -4
        contact_distance = distance_to(self, event.x, event.y)
        self._log(
            "hit.bot",
            target=event.victim_id,
            energy=round(event.energy, 1),
            rammed=event.rammed,
            x=round(self.x, 1),
            y=round(self.y, 1),
            target_x=round(event.x, 1),
            target_y=round(event.y, 1),
            distance=round(contact_distance, 1),
            near_wall=self._near_wall(),
            wall_risk=self._wall_risk(8),
            evade_direction=self._evade_direction,
        )

    def on_bot_death(self, event: BotDeathEvent) -> None:
        self._targets.pop(event.victim_id, None)
        self._gun.remove_target(event.victim_id)
        self._movement.remove_target(event.victim_id, clear_profile=False)
        self._enemy_gun_heat.remove_target(event.victim_id)
        if self._target_id == event.victim_id:
            self._target_id = None
        self._log("target.dead", bot_id=event.victim_id)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        wave = self._gun.record_pending_fire()
        target_id = wave.target_id if wave is not None else self._target_id
        target = self._targets.get(target_id) if target_id is not None else None
        target_age = self.turn_number - target.seen_turn if target is not None else None
        gun_score, gun_visits = self._gun.target_confidence(target_id) if target_id is not None else (0.0, 0)
        selected_gun_score, selected_gun_visits = (
            self._gun.mode_confidence(target_id, wave.aim_mode, wave.segment_key)
            if target_id is not None and wave is not None
            else (0.0, 0)
        )
        bullet_fields = self._fired_bullets.record(
            event.bullet.bullet_id,
            aim_mode=wave.aim_mode if wave is not None else None,
            aim_guess_factor=round(wave.aim_guess_factor, 3)
            if wave is not None and wave.aim_guess_factor is not None
            else None,
        )
        self._fire_telemetry.record_bullet_fired(
            event.bullet.bullet_id,
            target_id,
            event.bullet.power,
            event.bullet.direction,
            self.energy,
            self._gun.wave_count,
            self._gun.sample_count,
            gun_score,
            gun_visits,
            bullet_fields,
            target_age=target_age,
            target_x=target.x if target is not None else None,
            target_y=target.y if target is not None else None,
            selected_gun_confidence=selected_gun_score,
            selected_gun_confidence_visits=selected_gun_visits,
        )

    def _log(self, event: str, **fields: object) -> None:
        self._debug.log(event, **fields)

if __name__ == "__main__":
    ChaseLock().start()
