import math
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
    EnemyFireDetector,
    EnemyFirePowerPrediction,
    EnemyFirePowerPredictor,
    EnergyDropConfig,
    FireGate,
    FireGateConfig,
    GunHeatTracker,
)
from bot_core.gun import GunConfig, TargetMotion, VirtualGunSystem
from bot_core.movement import (
    FlatteningDecision,
    MinimumRiskConfig,
    MinimumRiskMovement,
    MovementCommand,
    MovementFlattener,
    MovementFlatteningConfig,
)
from bot_core.motion import OwnMotionTracker
from bot_core.radar import RadarLockConfig, lock_radar_to_target
from bot_core.tank_math import (
    TargetSnapshot,
    bearing_to,
    clamp,
    distance_to,
    drive_to_destination,
    target_from_hit_bot,
    target_from_scan,
)
from bot_core.targeting import TargetMemory, TargetSelector


@dataclass(frozen=True)
class FirePolicy:
    alignment_degrees: float = 7
    memory_turns: int = 1
    finish_target_energy: float = 14
    melee_finish_target_energy: float = 10
    finish_distance: float = 240
    enemy_fire_min_drop: float = 0.1
    enemy_fire_max_drop: float = 3.0
    enemy_fire_scan_gap_turns: int = 4
    enemy_fire_close_collision_distance: float = 75
    enemy_fire_close_collision_max_drop: float = 0.8
    enemy_fire_active_evasion_min_distance: float = 0
    melee_fire_active_evasion_min_distance: float = 0
    gun_heat_waves_active: bool = True
    gun_heat_wave_min_distance: float = 220
    gun_heat_wave_max_target_age: int = 2


@dataclass(frozen=True)
class TargetPolicy:
    memory_turns: int = 24
    reacquire_turns: int = 4
    drop_lost_turns: int = 9
    current_target_bonus: float = 58
    recent_threat_bonus: float = 82
    melee_current_target_bonus: float = 18
    melee_recent_threat_bonus: float = 34
    threat_memory_turns: int = 35


@dataclass(frozen=True)
class RadarPolicy:
    lock_rate: float = 24
    search_rate: float = 18
    reacquire_rate: float = 24
    lost_sweep_rate: float = 24
    gun_search_rate: float = 18
    reacquire_min_error: float = 8
    reacquire_overshoot: float = 8
    reacquire_widen_per_turn: float = 2
    reacquire_max_overshoot: float = 42
    lock_overscan: float = 12
    visible_reacquire_overscan: float = 18


@dataclass(frozen=True)
class MovementPolicy:
    preferred_min_distance: float = 360
    preferred_max_distance: float = 560
    melee_pressure_min_distance: float = 360
    melee_pressure_max_distance: float = 620
    panic_retreat_distance: float = 190
    melee_panic_retreat_distance: float = 245
    close_reset_distance: float = 330
    melee_close_reset_distance: float = 340
    field_margin: float = 18
    wall_margin: float = 90
    wall_lookahead_ticks: int = 11
    wall_escape_speed: float = 6
    approach_strafe_offset: float = 68
    orbit_strafe_offset: float = 92
    evade_strafe_offset: float = 102
    retreat_strafe_offset: float = 124
    evade_turns: int = 36
    flattener_active: bool = True
    goto_surfing_active: bool = True


@dataclass(frozen=True)
class DuelMovementPolicy:
    potential_step: float = 205.0
    preferred_distance: float = 580.0
    min_distance: float = 430.0
    max_distance: float = 730.0
    critical_distance: float = 300.0
    wall_margin: float = 130.0
    centering_margin: float = 245.0
    enemy_repel_weight: float = 1.65
    wall_repel_weight: float = 4.0
    orbit_weight: float = 1.15
    dodge_orbit_weight: float = 1.9
    range_attract_weight: float = 0.72
    center_attract_weight: float = 0.48
    threat_repel_weight: float = 0.68


FIRE_POLICY = FirePolicy()
TARGET_POLICY = TargetPolicy()
RADAR_POLICY = RadarPolicy()
MOVEMENT_POLICY = MovementPolicy()
DUEL_MOVEMENT_POLICY = DuelMovementPolicy()
RADAR_CONFIG = RadarLockConfig(
    search_rate=RADAR_POLICY.search_rate,
    lock_rate=RADAR_POLICY.lock_rate,
    reacquire_rate=RADAR_POLICY.reacquire_rate,
    reacquire_min_error=RADAR_POLICY.reacquire_min_error,
    lock_overscan=RADAR_POLICY.lock_overscan,
    reacquire_overscan=RADAR_POLICY.visible_reacquire_overscan,
)
ENERGY_DROP_CONFIG = EnergyDropConfig(
    min_fire_power=FIRE_POLICY.enemy_fire_min_drop,
    max_fire_power=FIRE_POLICY.enemy_fire_max_drop,
    max_scan_gap=FIRE_POLICY.enemy_fire_scan_gap_turns,
    close_collision_distance=FIRE_POLICY.enemy_fire_close_collision_distance,
    close_collision_max_drop=FIRE_POLICY.enemy_fire_close_collision_max_drop,
)
FIRE_GATE = FireGate(
    FireGateConfig(
        fire_memory_turns=FIRE_POLICY.memory_turns,
        alignment_degrees=FIRE_POLICY.alignment_degrees,
        energy_margin=5,
    )
)


class AdaptivePrime(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Adaptive Prime",
                version="1.0",
                authors=["robocode-bot"],
                description="Adaptive composite bot with virtual guns, enemy-fire prediction, wave-aware movement, bullet shadows, and minimum-risk routing.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._targets = TargetMemory()
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
        self._own_motion = OwnMotionTracker()
        self._melee_round = False
        self._enemy_gun_heat = GunHeatTracker()
        self._enemy_fire_power = EnemyFirePowerPredictor()
        self._last_enemy_power_prediction: dict[int, EnemyFirePowerPrediction] = {}
        self._enemy_fire_detector = EnemyFireDetector(
            ENERGY_DROP_CONFIG,
            self._enemy_energy_corrections,
            self._enemy_gun_heat,
            self._enemy_fire_power,
            self._last_enemy_power_prediction,
        )
        self._target_selector = TargetSelector(TARGET_POLICY.reacquire_turns)
        self._gun = VirtualGunSystem(
            GunConfig(selectable_modes=frozenset({"linear", "traditional_gf", "dynamic_cluster", "anti_surfer"}))
        )
        self._movement = MovementFlattener(
            MovementFlatteningConfig(
                bullet_shadow_enabled=True,
                goto_use_expected_waves=True,
                goto_expected_wave_min_confidence=0.62,
            )
        )
        self._minimum_risk = MinimumRiskMovement(
            MinimumRiskConfig(
                candidate_distances=(220.0, 320.0, 430.0, 560.0),
                field_margin=105.0,
                preferred_target_distance=500.0,
                max_target_distance=780.0,
                close_enemy_distance=330.0,
                travel_weight=0.0009,
                enemy_weight=36000.0,
                close_enemy_weight=55.0,
                target_distance_weight=0.0002,
                threat_lateral_weight=2.2,
                threat_distance_weight=12000.0,
                destination_commit_ticks=8,
                destination_switch_risk_ratio=0.86,
            )
        )
        self._debug = DebugLogger(self, "adaptive-prime")
        self._fired_bullets = FiredBulletTracker()

    def run(self) -> None:
        self.body_color = Color.from_rgb(60, 112, 180)
        self.turret_color = Color.from_rgb(36, 64, 105)
        self.radar_color = Color.from_rgb(190, 225, 255)
        self.bullet_color = Color.from_rgb(255, 230, 120)
        self.scan_color = Color.from_rgb(150, 205, 255)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.max_speed = 8

        while self.running:
            self._update_own_motion_stats()
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
            self._log(
                "scan.new",
                bot_id=event.scanned_bot_id,
                energy=round(event.energy, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )
        elif previous_age is not None and previous_age > TARGET_POLICY.reacquire_turns:
            self._log(
                "scan.reacquired",
                bot_id=event.scanned_bot_id,
                previous_age=previous_age,
                previous_x=round(previous.x, 1),
                previous_y=round(previous.y, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )

    def _update_target_motion_stats(self, event: ScannedBotEvent, previous: TargetSnapshot) -> None:
        speed_delta = event.speed - previous.speed
        self._target_accel[event.scanned_bot_id] = speed_delta
        direction_delta = abs(((event.direction - previous.direction + 180) % 360) - 180)
        if abs(speed_delta) > 0.35 or direction_delta > 7:
            self._last_velocity_change_turn[event.scanned_bot_id] = self.turn_number

    def _detect_enemy_fire(self, event: ScannedBotEvent, previous: TargetSnapshot, scan_gap: int) -> bool:
        distance = distance_to(self, event.x, event.y)
        detection = self._enemy_fire_detector.evaluate_scan(
            event.scanned_bot_id,
            previous.energy,
            event.energy,
            previous.seen_turn,
            self.turn_number,
            scan_gap,
            distance,
            self.energy,
            self.gun_cooling_rate,
        )
        signal = detection.signal
        if not signal.is_fire:
            if signal.raw_energy_drop > 0 or signal.energy_correction:
                self._log(
                    "enemy.energy_drop_ignored",
                    bot_id=event.scanned_bot_id,
                    reason=signal.reason,
                    raw_drop=round(signal.raw_energy_drop, 2),
                    corrected_drop=round(signal.energy_drop, 2),
                    correction=round(signal.energy_correction, 2),
                    scan_gap=scan_gap,
                    distance=round(distance, 1),
                    previous_energy=round(previous.energy, 1),
                    energy=round(event.energy, 1),
                )
            return False

        self._recent_threat_id = event.scanned_bot_id
        self._recent_threat_turn = self.turn_number
        self._last_enemy_fire_turn = self.turn_number
        previous_prediction = detection.previous_prediction
        heat_state = detection.heat_state
        movement_wave = self._movement.record_enemy_fire(
            self,
            target_from_scan(event, self.turn_number),
            signal.fire_power or 1.5,
            **self._own_motion.movement_wave_kwargs(self.turn_number),
        )
        melee_active = self._melee_round or self.enemy_count > 1 or len(self._targets) > 1
        active_evasion = (
            distance >= FIRE_POLICY.enemy_fire_active_evasion_min_distance
            if not melee_active
            else distance >= FIRE_POLICY.melee_fire_active_evasion_min_distance
        )
        if active_evasion:
            if melee_active and not self._wall_risk(8):
                self._evade_direction *= -1
            self._evade_until_turn = max(self._evade_until_turn, self.turn_number + signal.evade_ticks)
        self._log(
            "enemy.fire_detected",
            bot_id=event.scanned_bot_id,
            power=round(signal.fire_power or 0.0, 2),
            raw_drop=round(signal.raw_energy_drop, 2),
            corrected_drop=round(signal.energy_drop, 2),
            correction=round(signal.energy_correction, 2),
            scan_gap=scan_gap,
            distance=round(distance, 1),
            bullet_travel_ticks=signal.bullet_travel_ticks,
            previous_energy=round(previous.energy, 1),
            energy=round(event.energy, 1),
            evasion=("active_melee" if melee_active else "active_duel") if active_evasion else "threat_only",
            evade_direction=self._evade_direction,
            evade_until=self._evade_until_turn,
            known_targets=len(self._targets),
            movement_wave=movement_wave is not None,
            gun_heat=round(heat_state.heat, 2) if heat_state is not None else None,
            predicted_power=round(previous_prediction.fire_power, 2) if previous_prediction is not None else None,
            prediction_error=round(abs(previous_prediction.fire_power - (signal.fire_power or 1.5)), 2)
            if previous_prediction is not None
            else None,
            power_samples=self._enemy_fire_power.sample_count(event.scanned_bot_id),
            power_mae=round(self._enemy_fire_power.mean_absolute_error(event.scanned_bot_id), 3)
            if self._enemy_fire_power.mean_absolute_error(event.scanned_bot_id) is not None
            else None,
        )
        return True

    def _record_gun_heat_wave(self, target: TargetSnapshot) -> None:
        if not FIRE_POLICY.gun_heat_waves_active:
            return
        age = self.turn_number - target.seen_turn
        distance = distance_to(self, target.x, target.y)
        if len(self._targets) > 1 or age > FIRE_POLICY.gun_heat_wave_max_target_age or distance < FIRE_POLICY.gun_heat_wave_min_distance:
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
        self._log(
            "enemy.gun_heat_wave",
            bot_id=target.bot_id,
            power=round(fire_power, 2),
            confidence=round(prediction.confidence, 3),
            samples=prediction.samples,
            reason=prediction.reason,
            power_mae=round(prediction.mean_absolute_error, 3)
            if prediction.mean_absolute_error is not None
            else None,
            distance=round(distance, 1),
            target_age=age,
            movement_wave=movement_wave is not None,
        )

    def _track_or_search(self) -> None:
        self._reset_if_new_round()
        self._forget_stale_targets()
        self._log_movement_profile_visits()
        target = self._select_target()
        if target is None:
            self._search()
            self._sample_status("search", known_targets=0)
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
            MOVEMENT_POLICY.field_margin,
            allow_traditional_gf=use_segmented_gun_stats,
            allow_segmented_stats=use_segmented_gun_stats,
        )
        score_segment = aim.segment_key if use_segmented_gun_stats else None
        if aim.mode_changed:
            self._log(
                "gun.switch",
                target=target.bot_id,
                previous=aim.previous_mode,
                selected=aim.mode,
                scores=self._gun.score_summary(target.bot_id, score_segment),
            )
        age = self.turn_number - target.seen_turn

        if age > TARGET_POLICY.reacquire_turns:
            if age > TARGET_POLICY.drop_lost_turns:
                self._drop_lost_target(target, age, distance)
                return

            radar_turn, radar_mode = self._set_lost_target_radar(radar_bearing, age)
            self._set_gun_for_search()
            self._set_search_movement()
            self._sample_status(
                "target.reacquire",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                radar_bearing=round(radar_bearing, 2),
                radar_direction=round(self.radar_direction, 2),
                radar_turn=round(radar_turn, 2),
                radar_mode=radar_mode,
                radar_sweep=self._radar_sweep_direction,
                x=round(self.x, 1),
                y=round(self.y, 1),
                known_targets=len(self._targets),
            )
            return

        radar_command = lock_radar_to_target(self, target, RADAR_CONFIG)
        if abs(radar_command.turn) >= 1:
            self._radar_sweep_direction = 1 if radar_command.turn > 0 else -1
        self.set_turn_gun_left(aim.gun_bearing)

        movement_mode, strafe_offset, flattening = self._set_adaptive_movement(target, distance, body_bearing)

        fire_decision = FIRE_GATE.decide(age, distance, aim.gun_bearing, firepower, self.energy)
        if fire_decision.can_fire:
            self._gun.set_pending_wave(self._gun.make_wave(self, target, firepower, aim))
            self.set_fire(firepower)
        else:
            self._sample_status(
                "track",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                gun_bearing=round(aim.gun_bearing, 2),
                radar_bearing=round(radar_command.bearing, 2),
                radar_turn=round(radar_command.turn, 2),
                radar_mode=radar_command.mode,
                radar_age=radar_command.age,
                predicted_x=round(aim.predicted_x, 1),
                predicted_y=round(aim.predicted_y, 1),
                aim_mode=aim.mode,
                aim_guess_factor=round(aim.guess_factor, 3) if aim.guess_factor is not None else None,
                gun_samples=self._gun.sample_count,
                gun_scores=self._gun.score_summary(target.bot_id, score_segment),
                fire_alignment_limit=fire_decision.alignment_limit,
                hold_reason=fire_decision.reason,
                evade_direction=self._evade_direction,
                evading=self.turn_number <= self._evade_until_turn,
                movement_mode=movement_mode if "movement_mode" in locals() else "wall",
                strafe_offset=round(strafe_offset, 1) if "strafe_offset" in locals() else None,
                flatten_reason=flattening.reason if "flattening" in locals() and flattening is not None else None,
                flatten_bucket=flattening.bucket if "flattening" in locals() and flattening is not None else None,
                last_enemy_fire_age=self.turn_number - self._last_enemy_fire_turn,
                known_targets=len(self._targets),
            )

    def _set_adaptive_movement(
        self,
        target: TargetSnapshot,
        distance: float,
        body_bearing: float,
    ) -> tuple[str, float, FlatteningDecision | None]:
        evading = self.turn_number <= self._evade_until_turn
        duel_active = len(self._targets) <= 1 and self.enemy_count <= 1
        panic_distance = MOVEMENT_POLICY.panic_retreat_distance if len(self._targets) <= 1 else MOVEMENT_POLICY.melee_panic_retreat_distance
        if not duel_active and distance < panic_distance:
            command = MovementCommand.strafe(
                "panic_retreat",
                body_bearing,
                MOVEMENT_POLICY.retreat_strafe_offset,
                self._evade_direction,
                -7,
            )
            self._apply_movement_command(command)
            return command.mode, command.strafe_offset, None

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
                command = MovementCommand.drive_to_destination(
                    self,
                    decision.x,
                    decision.y,
                    8,
                    "melee_minimum_risk",
                )
                self._apply_movement_command(command)
                self._sample_status(
                    "movement.minimum_risk",
                    target=target.bot_id,
                    destination_x=round(decision.x, 1),
                    destination_y=round(decision.y, 1),
                    risk=round(decision.risk, 3),
                    candidates=decision.candidates,
                    nearest_enemy=decision.nearest_enemy_id,
                    nearest_enemy_distance=round(decision.nearest_enemy_distance, 1),
                    reused_destination=decision.reused,
                    destination_age=decision.age,
                    fire_threat=threat_target.bot_id if threat_target is not None else None,
                    turn=round(command.turn, 2),
                    speed=command.speed,
                    known_targets=len(self._targets),
                )
                return command.mode, command.strafe_offset, None

        if duel_active:
            flattening = self._movement.choose_direction(
                self,
                body_bearing,
                MOVEMENT_POLICY.evade_strafe_offset if evading else MOVEMENT_POLICY.orbit_strafe_offset,
                8,
                MOVEMENT_POLICY.field_margin,
                target.bot_id,
                distance,
                self._evade_direction,
                self.turn_number,
                allow_switch=True,
                use_surfing=True,
            )
            if flattening.changed:
                self._log(
                    "movement.duel_flatten",
                    target=target.bot_id,
                    current_direction=self._evade_direction,
                    suggested_direction=flattening.direction,
                    bucket=flattening.bucket,
                    current_count=round(flattening.current_count, 1),
                    alternative_count=round(flattening.alternative_count, 1),
                    distance=round(distance, 1),
                    reason=flattening.reason,
                )
                if MOVEMENT_POLICY.flattener_active and flattening.current_count >= 2.0:
                    self._evade_direction = flattening.direction
            if MOVEMENT_POLICY.goto_surfing_active:
                surf_decision = self._movement.choose_go_to_surf_destination(
                    self,
                    target,
                    max_speed=8,
                    field_margin=DUEL_MOVEMENT_POLICY.wall_margin,
                )
                if surf_decision is not None:
                    command = MovementCommand.drive_to_destination(
                        self,
                        surf_decision.x,
                        surf_decision.y,
                        8,
                        "goto_surf",
                        direction_update=surf_decision.direction or None,
                    )
                    self._apply_movement_command(command)
                    self._sample_status(
                        "movement.goto_surf",
                        target=target.bot_id,
                        destination_x=round(surf_decision.x, 1),
                        destination_y=round(surf_decision.y, 1),
                        danger=round(surf_decision.danger, 3),
                        profile_danger=round(surf_decision.profile_danger, 3),
                        ensemble_danger=round(surf_decision.ensemble_danger, 3),
                        ensemble_samples=round(surf_decision.ensemble_samples, 1),
                        ensemble_weight=round(surf_decision.ensemble_weight, 3),
                        wall_risk=round(surf_decision.wall_risk, 3),
                        distance_risk=round(surf_decision.distance_risk, 3),
                        travel_risk=round(surf_decision.travel_risk, 3),
                        candidates=surf_decision.candidates,
                        wave_kind=surf_decision.wave_kind,
                        hit_guess_factor=round(surf_decision.hit_guess_factor, 3),
                        hit_bin=surf_decision.hit_bin,
                        hit_turn=surf_decision.hit_turn,
                        evade_direction=self._evade_direction,
                        turn=round(command.turn, 2),
                        speed=command.speed,
                    )
                    return command.mode, command.strafe_offset, flattening
            destination_x, destination_y, force_x, force_y, movement_mode = self._duel_potential_destination(
                target,
                distance,
                evading,
            )
            command = MovementCommand.drive_to_destination(
                self,
                destination_x,
                destination_y,
                8,
                movement_mode,
            )
            self._apply_movement_command(command)
            self._sample_status(
                "movement.duel_potential",
                target=target.bot_id,
                destination_x=round(destination_x, 1),
                destination_y=round(destination_y, 1),
                force_x=round(force_x, 3),
                force_y=round(force_y, 3),
                distance=round(distance, 1),
                mode=movement_mode,
                evading=evading,
                evade_direction=self._evade_direction,
                turn=round(command.turn, 2),
                speed=command.speed,
            )
            return command.mode, command.strafe_offset, flattening

        movement_mode, strafe_offset, move_speed = self._movement_command(target, distance, evading)
        flattening = self._movement.choose_direction(
            self,
            body_bearing,
            strafe_offset,
            move_speed,
            MOVEMENT_POLICY.field_margin,
            target.bot_id,
            distance,
            self._evade_direction,
            self.turn_number,
            allow_switch=len(self._targets) <= 1,
            use_surfing=not self._melee_round,
        )
        if flattening.changed:
            self._log(
                "movement.flatten" if MOVEMENT_POLICY.flattener_active else "movement.flatten_shadow",
                target=target.bot_id,
                current_direction=self._evade_direction,
                suggested_direction=flattening.direction,
                bucket=flattening.bucket,
                current_count=round(flattening.current_count, 1),
                alternative_count=round(flattening.alternative_count, 1),
                distance=round(distance, 1),
            )
            if MOVEMENT_POLICY.flattener_active:
                self._evade_direction = flattening.direction

        command = MovementCommand.strafe(
            movement_mode,
            body_bearing,
            strafe_offset,
            self._evade_direction,
            move_speed,
        )
        self._apply_movement_command(command)
        return command.mode, command.strafe_offset, flattening

    def _apply_movement_command(self, command: MovementCommand) -> None:
        if command.direction_update is not None:
            self._evade_direction = command.direction_update
        command.apply(self)

    def _movement_command(self, target: TargetSnapshot, distance: float, evading: bool) -> tuple[str, float, float]:
        if self._melee_round and self.enemy_count > 1:
            return self._melee_movement_command(target, distance, evading)

        if target.energy <= FIRE_POLICY.finish_target_energy and distance > FIRE_POLICY.finish_distance:
            return "finish_close", MOVEMENT_POLICY.approach_strafe_offset, 8

        if distance < MOVEMENT_POLICY.close_reset_distance:
            return "reset_range", MOVEMENT_POLICY.retreat_strafe_offset, 7

        if distance < MOVEMENT_POLICY.preferred_min_distance:
            return "open_range", MOVEMENT_POLICY.retreat_strafe_offset, 7

        if distance > MOVEMENT_POLICY.preferred_max_distance:
            return "approach_orbit", MOVEMENT_POLICY.approach_strafe_offset, 8

        if evading:
            return "evade_orbit", MOVEMENT_POLICY.evade_strafe_offset, 7

        return "mid_orbit", MOVEMENT_POLICY.orbit_strafe_offset, 7

    def _duel_potential_destination(
        self,
        target: TargetSnapshot,
        distance: float,
        evading: bool,
    ) -> tuple[float, float, float, float, str]:
        distance = max(1.0, distance)
        enemy_to_self_x = (self.x - target.x) / distance
        enemy_to_self_y = (self.y - target.y) / distance
        self_to_enemy_x = -enemy_to_self_x
        self_to_enemy_y = -enemy_to_self_y
        tangent_x = -enemy_to_self_y * self._evade_direction
        tangent_y = enemy_to_self_x * self._evade_direction

        force_x = 0.0
        force_y = 0.0
        mode = "duel_potential_orbit"

        if distance < DUEL_MOVEMENT_POLICY.preferred_distance:
            close_ratio = (DUEL_MOVEMENT_POLICY.preferred_distance - distance) / DUEL_MOVEMENT_POLICY.preferred_distance
            repel = DUEL_MOVEMENT_POLICY.enemy_repel_weight * (0.4 + close_ratio * close_ratio * 3.0)
            if distance < DUEL_MOVEMENT_POLICY.critical_distance:
                repel *= 2.0
                mode = "duel_potential_panic"
            elif distance < DUEL_MOVEMENT_POLICY.min_distance:
                mode = "duel_potential_open_range"
            force_x += enemy_to_self_x * repel
            force_y += enemy_to_self_y * repel
        elif distance > DUEL_MOVEMENT_POLICY.max_distance:
            far_ratio = min(1.0, (distance - DUEL_MOVEMENT_POLICY.max_distance) / DUEL_MOVEMENT_POLICY.max_distance)
            attract = DUEL_MOVEMENT_POLICY.range_attract_weight * (0.35 + far_ratio)
            force_x += self_to_enemy_x * attract
            force_y += self_to_enemy_y * attract
            mode = "duel_potential_reconnect"

        orbit = DUEL_MOVEMENT_POLICY.dodge_orbit_weight if evading else DUEL_MOVEMENT_POLICY.orbit_weight
        if distance < DUEL_MOVEMENT_POLICY.min_distance:
            orbit *= 0.75
        elif distance > DUEL_MOVEMENT_POLICY.max_distance:
            orbit *= 0.55
        force_x += tangent_x * orbit
        force_y += tangent_y * orbit

        threat = self._active_fire_threat()
        if threat is not None and threat.bot_id == target.bot_id:
            fire_age = self.turn_number - self._recent_threat_turn
            urgency = max(0.25, 1.0 - fire_age / max(1.0, TARGET_POLICY.threat_memory_turns))
            force_x += enemy_to_self_x * DUEL_MOVEMENT_POLICY.threat_repel_weight * urgency
            force_y += enemy_to_self_y * DUEL_MOVEMENT_POLICY.threat_repel_weight * urgency
            force_x += tangent_x * DUEL_MOVEMENT_POLICY.dodge_orbit_weight * urgency
            force_y += tangent_y * DUEL_MOVEMENT_POLICY.dodge_orbit_weight * urgency
            mode = "duel_potential_dodge"

        wall_force_x, wall_force_y = self._wall_potential_force()
        force_x += wall_force_x
        force_y += wall_force_y

        if self._near_wall_margin(DUEL_MOVEMENT_POLICY.centering_margin):
            center_x = self.arena_width / 2
            center_y = self.arena_height / 2
            center_distance = max(1.0, math.hypot(center_x - self.x, center_y - self.y))
            force_x += (center_x - self.x) / center_distance * DUEL_MOVEMENT_POLICY.center_attract_weight
            force_y += (center_y - self.y) / center_distance * DUEL_MOVEMENT_POLICY.center_attract_weight

        magnitude = math.hypot(force_x, force_y)
        if magnitude < 0.001:
            force_x = tangent_x
            force_y = tangent_y
            magnitude = 1.0

        step = DUEL_MOVEMENT_POLICY.potential_step
        if evading or distance < DUEL_MOVEMENT_POLICY.min_distance:
            step += 45.0
        if self._near_wall_margin(DUEL_MOVEMENT_POLICY.centering_margin):
            step += 35.0

        destination_x = self.x + force_x / magnitude * step
        destination_y = self.y + force_y / magnitude * step
        destination_x, destination_y = self._clamp_duel_destination(destination_x, destination_y)
        return destination_x, destination_y, force_x, force_y, mode

    def _wall_potential_force(self) -> tuple[float, float]:
        left = max(1.0, self.x)
        right = max(1.0, self.arena_width - self.x)
        bottom = max(1.0, self.y)
        top = max(1.0, self.arena_height - self.y)

        force_x = DUEL_MOVEMENT_POLICY.wall_repel_weight * (
            self._wall_axis_force(left, DUEL_MOVEMENT_POLICY.wall_margin) - self._wall_axis_force(right, DUEL_MOVEMENT_POLICY.wall_margin)
        )
        force_y = DUEL_MOVEMENT_POLICY.wall_repel_weight * (
            self._wall_axis_force(bottom, DUEL_MOVEMENT_POLICY.wall_margin) - self._wall_axis_force(top, DUEL_MOVEMENT_POLICY.wall_margin)
        )
        return force_x, force_y

    def _wall_axis_force(self, distance: float, margin: float) -> float:
        if distance >= margin:
            return 0.0
        closeness = (margin - distance) / margin
        return 0.35 + closeness * closeness * 4.0

    def _clamp_duel_destination(self, x: float, y: float) -> tuple[float, float]:
        margin = DUEL_MOVEMENT_POLICY.wall_margin
        return (
            clamp(x, margin, self.arena_width - margin),
            clamp(y, margin, self.arena_height - margin),
        )

    def _near_wall_margin(self, margin: float) -> bool:
        return (
            self.x < margin
            or self.x > self.arena_width - margin
            or self.y < margin
            or self.y > self.arena_height - margin
        )

    def _melee_movement_command(
        self,
        target: TargetSnapshot,
        distance: float,
        evading: bool,
    ) -> tuple[str, float, float]:
        if target.energy <= FIRE_POLICY.melee_finish_target_energy and distance > FIRE_POLICY.finish_distance:
            return "melee_finish_close", MOVEMENT_POLICY.approach_strafe_offset, 8

        if distance < MOVEMENT_POLICY.melee_close_reset_distance:
            return "melee_reset_range", MOVEMENT_POLICY.retreat_strafe_offset, 7

        if distance > MOVEMENT_POLICY.melee_pressure_max_distance:
            return "melee_pressure_close", MOVEMENT_POLICY.approach_strafe_offset, 8

        if distance < MOVEMENT_POLICY.melee_pressure_min_distance:
            return "melee_open_range", MOVEMENT_POLICY.orbit_strafe_offset, 7

        if evading:
            return "melee_evade_pressure", MOVEMENT_POLICY.evade_strafe_offset, 7

        return "melee_pressure_orbit", MOVEMENT_POLICY.approach_strafe_offset, 8

    def _select_firepower(self, target: TargetSnapshot, distance: float) -> float:
        if self._melee_round and self.enemy_count > 1:
            return self._select_melee_firepower(target, distance)

        if self.energy <= 18:
            return 0.8 if distance < 260 else 0.6
        if target.energy <= FIRE_POLICY.finish_target_energy and distance < 320:
            return min(2.2, max(0.6, target.energy / 3.5 + 0.2))

        gun_score, gun_visits = self._gun.target_confidence(target.bot_id)
        if distance < 160:
            return 2.2 if self.energy > 36 else 1.6
        if distance < 280:
            return 1.8
        if distance < 420 and (gun_visits >= 45 or self.energy > target.energy + 12):
            return 1.6
        if distance < 420:
            return 1.3
        if distance < 620 and (gun_visits >= 70 and gun_score >= 0.28 or self.energy > target.energy + 18):
            return 1.3
        if distance < 620:
            return 1.0
        return 0.8

    def _select_melee_firepower(self, target: TargetSnapshot, distance: float) -> float:
        if self.energy <= 16:
            return 0.8 if distance < 220 else 0.6
        if target.energy <= FIRE_POLICY.melee_finish_target_energy and distance < 260:
            return min(2.2, max(0.8, target.energy / 3.2 + 0.2))

        gun_score, gun_visits = self._gun.target_confidence(target.bot_id)
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

    def _update_own_motion_stats(self) -> None:
        self._own_motion.update(self)

    def _log_wave_visits(self, target: TargetSnapshot) -> None:
        for visit in self._gun.update_waves(self, target):
            self._log(
                "gun.wave_visit",
                target=visit.target_id,
                guess_factor=round(visit.guess_factor, 3),
                samples=visit.samples,
                traveled=round(visit.traveled, 1),
                distance=round(visit.distance, 1),
                selected_gun=visit.selected_gun,
                virtual_scores=visit.virtual_scores,
                gun_scores=visit.gun_scores,
            )

    def _log_movement_profile_visits(self) -> None:
        for visit in self._movement.update(self):
            self._log(
                "movement.profile_visit",
                target=visit.target_id,
                guess_factor=round(visit.guess_factor, 3),
                bin=visit.bin_index,
                bucket=visit.bucket,
                visits=round(visit.visits, 1),
                wave_age=visit.wave_age,
                ensemble_danger=round(visit.ensemble_danger, 3),
                ensemble_samples=round(visit.ensemble_samples, 1),
            )

    def _set_lost_target_radar(self, radar_bearing: float, age: int) -> tuple[float, str]:
        if abs(radar_bearing) > RADAR_POLICY.reacquire_min_error:
            overshoot = min(
                RADAR_POLICY.reacquire_max_overshoot,
                RADAR_POLICY.reacquire_overshoot + age * RADAR_POLICY.reacquire_widen_per_turn,
            )
            direction = 1 if radar_bearing > 0 else -1
            radar_turn = clamp(
                radar_bearing + overshoot * direction,
                -RADAR_POLICY.lost_sweep_rate,
                RADAR_POLICY.lost_sweep_rate,
            )
            self._radar_sweep_direction = direction
            self.set_turn_radar_left(radar_turn)
            return radar_turn, "cached_bearing"

        radar_turn = RADAR_POLICY.lost_sweep_rate * self._radar_sweep_direction
        self.set_turn_radar_left(radar_turn)
        return radar_turn, "widen"

    def _sample_status(self, event: str, **fields: object) -> None:
        self._debug.sample(event, **fields)

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

    def _drop_lost_target(self, target: TargetSnapshot, age: int, distance: float) -> None:
        self._targets.pop(target.bot_id, None)
        self._movement.remove_target(target.bot_id, clear_profile=False)
        self._enemy_fire_detector.remove_target(target.bot_id)
        if self._target_id == target.bot_id:
            self._target_id = None
        self._search()
        self._log(
            "target.drop_lost",
            bot_id=target.bot_id,
            age=age,
            cached_x=round(target.x, 1),
            cached_y=round(target.y, 1),
            cached_distance=round(distance, 1),
            known_targets=len(self._targets),
        )

    def _forget_stale_targets(self) -> None:
        stale_ids = self._targets.stale_ids(self.turn_number, TARGET_POLICY.memory_turns)
        for bot_id in stale_ids:
            self._log("target.stale", bot_id=bot_id)
            del self._targets[bot_id]
            self._movement.remove_target(bot_id, clear_profile=False)
        if self._target_id not in self._targets:
            self._target_id = None

    def _select_target(self) -> TargetSnapshot | None:
        selection = self._target_selector.select(
            self._targets,
            self._target_id,
            self.turn_number,
            self._target_score,
        )
        if selection is None:
            self._target_id = None
            return None

        target = selection.target
        self._target_id = target.bot_id
        if selection.changed:
            self._log(
                "target.select",
                previous=selection.previous_id,
                selected=target.bot_id,
                score=round(selection.score, 1),
                fresh_candidates=selection.fresh_candidates,
                known_targets=len(self._targets),
            )
        return target

    def _target_score(self, target: TargetSnapshot) -> float:
        distance = distance_to(self, target.x, target.y)
        age = self.turn_number - target.seen_turn
        threat_is_fresh = (
            target.bot_id == self._recent_threat_id
            and self.turn_number - self._recent_threat_turn <= TARGET_POLICY.threat_memory_turns
        )
        if self._melee_round and self.enemy_count > 1:
            current_bonus = TARGET_POLICY.melee_current_target_bonus if target.bot_id == self._target_id else 0
            recent_threat_bonus = TARGET_POLICY.melee_recent_threat_bonus if threat_is_fresh else 0
            return distance * 0.45 + target.energy * 2.0 + age * 92 - current_bonus - recent_threat_bonus

        current_bonus = TARGET_POLICY.current_target_bonus if target.bot_id == self._target_id else 0
        recent_threat_bonus = TARGET_POLICY.recent_threat_bonus if threat_is_fresh else 0
        return distance * 0.7 + target.energy * 2.5 + age * 60 - current_bonus - recent_threat_bonus

    def _active_fire_threat(self) -> TargetSnapshot | None:
        return self._targets.active_fire_threat(
            self._recent_threat_id,
            self._recent_threat_turn,
            self.turn_number,
            TARGET_POLICY.threat_memory_turns,
        )

    def _record_enemy_energy_correction(self, target_id: int, correction: float, reason: str) -> None:
        self._enemy_fire_detector.record_correction(target_id, self.turn_number, correction, reason)

    def _consume_enemy_energy_correction(self, target_id: int, current_turn: int, after_turn: int) -> float:
        return self._enemy_fire_detector.consume_correction(target_id, current_turn, after_turn)

    def _search(self) -> None:
        self._set_search_movement()
        self._set_gun_for_search()
        self.radar_turn_rate = RADAR_POLICY.search_rate

    def _drive_to_destination(self, x: float, y: float, speed: float) -> tuple[float, float]:
        return drive_to_destination(self, x, y, speed)

    def _set_gun_for_search(self) -> None:
        gun_to_radar = ((self.radar_direction - self.gun_direction + 180) % 360) - 180
        if abs(gun_to_radar) > 5:
            self.set_turn_gun_left(clamp(gun_to_radar, -RADAR_POLICY.gun_search_rate, RADAR_POLICY.gun_search_rate))
        else:
            self.gun_turn_rate = RADAR_POLICY.gun_search_rate * self._radar_sweep_direction

    def _set_search_movement(self) -> None:
        if self._near_wall() or self._wall_risk(6):
            center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
            self.target_speed = MOVEMENT_POLICY.wall_escape_speed
            self.set_turn_left(clamp(center_bearing, -35, 35))
            self._sample_status(
                "search.wall_avoid",
                x=round(self.x, 1),
                y=round(self.y, 1),
                center_bearing=round(center_bearing, 2),
                evade_direction=self._evade_direction,
                near_wall=self._near_wall(),
            )
            return

        self.target_speed = 4 * self._evade_direction
        self.turn_rate = 3 * self._evade_direction

    def _wall_risk(self, speed: float) -> bool:
        heading = math.radians(self.direction)
        projected_x = self.x + math.cos(heading) * speed * MOVEMENT_POLICY.wall_lookahead_ticks
        projected_y = self.y + math.sin(heading) * speed * MOVEMENT_POLICY.wall_lookahead_ticks
        return (
            projected_x < MOVEMENT_POLICY.wall_margin
            or projected_x > self.arena_width - MOVEMENT_POLICY.wall_margin
            or projected_y < MOVEMENT_POLICY.wall_margin
            or projected_y > self.arena_height - MOVEMENT_POLICY.wall_margin
        )

    def _near_wall(self) -> bool:
        return (
            self.x < MOVEMENT_POLICY.wall_margin
            or self.x > self.arena_width - MOVEMENT_POLICY.wall_margin
            or self.y < MOVEMENT_POLICY.wall_margin
            or self.y > self.arena_height - MOVEMENT_POLICY.wall_margin
        )

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + MOVEMENT_POLICY.evade_turns
        center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
        self.target_speed = MOVEMENT_POLICY.wall_escape_speed
        self.set_turn_left(clamp(center_bearing, -35, 35))
        self._log("hit.wall", evade_direction=self._evade_direction, center_bearing=round(center_bearing, 2))

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._wall_risk(8):
            self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + MOVEMENT_POLICY.evade_turns
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
        self._movement.remove_shadow_bullet(event.bullet.bullet_id)
        bullet_fields = self._fired_bullets.fields_for(event.bullet.bullet_id)
        self._log(
            "bullet.hit_bot",
            victim=event.victim_id,
            bullet_id=event.bullet.bullet_id,
            power=round(event.bullet.power, 2),
            damage=round(event.damage, 2),
            energy=round(event.energy, 1),
            **bullet_fields,
        )

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._targets[event.victim_id] = target_from_hit_bot(event, self.turn_number)
        if not self._melee_round:
            self._target_id = event.victim_id
        self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + MOVEMENT_POLICY.evade_turns
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
        self._last_enemy_power_prediction.pop(event.victim_id, None)
        if self._target_id == event.victim_id:
            self._target_id = None
        self._log("target.dead", bot_id=event.victim_id)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        target = self._targets.get(self._target_id)
        target_age = self.turn_number - target.seen_turn if target is not None else None
        gun_score, gun_visits = self._gun.target_confidence(target.bot_id) if target is not None else (0.0, 0)
        wave = self._gun.record_pending_fire()
        self._movement.record_shadow_bullet(
            self,
            event.bullet.bullet_id,
            event.bullet.power,
            event.bullet.direction,
        )
        bullet_fields = self._fired_bullets.record(
            event.bullet.bullet_id,
            aim_mode=wave.aim_mode if wave is not None else None,
            aim_guess_factor=round(wave.aim_guess_factor, 3)
            if wave is not None and wave.aim_guess_factor is not None
            else None,
        )
        self._log(
            "bullet.fired",
            bullet_id=event.bullet.bullet_id,
            target=self._target_id,
            target_age=target_age,
            target_x=round(target.x, 1) if target is not None else None,
            target_y=round(target.y, 1) if target is not None else None,
            power=event.bullet.power,
            direction=round(event.bullet.direction, 1),
            energy=round(self.energy, 1),
            gun_waves=self._gun.wave_count,
            shadow_bullets=self._movement.shadow_bullet_count,
            gun_samples=self._gun.sample_count,
            gun_confidence=round(gun_score, 3),
            gun_confidence_visits=gun_visits,
            **bullet_fields,
        )

    def _log(self, event: str, **fields: object) -> None:
        self._debug.log(event, **fields)

if __name__ == "__main__":
    AdaptivePrime().start()
