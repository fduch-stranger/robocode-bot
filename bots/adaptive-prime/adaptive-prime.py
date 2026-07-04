import math
from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BotDeathEvent,
    BulletFiredEvent,
    BulletHitBotEvent,
    GameStartedEvent,
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
    FireDecision,
    GunHeatTracker,
)
from bot_core.gun import (
    AimSolution,
    GunScoringConfig,
    GunSystemConfig,
    TargetMotion,
    VirtualGunSystem,
    dynamic_cluster_config_from_policy,
    gun_policy_status_fields,
    selector_config_from_policy,
    should_log_switch_decision,
)
from bot_core.gun.factory import standard_runtime_config
from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.movement import (
    FlatteningDecision,
    MinimumRiskConfig,
    MinimumRiskMovement,
    MovementCommand,
    MovementFlattener,
    MovementFlatteningConfig,
)
from bot_core.motion import OwnMotionTracker
from bot_core.radar import lock_radar_to_target
from bot_core.geometry.angles import bearing_to
from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to
from bot_core.movement.navigation import drive_to_destination
from bot_core.target_snapshot import TargetSnapshot, interpolate_target, target_from_hit_bot, target_from_scan
from bot_core.targeting import TargetMemory, TargetSelector
from bot_core.telemetry.energy import EnergyTelemetry
from bot_core.telemetry.fire import FireTelemetry, FireTick
from bot_core.telemetry.movement import MovementTelemetry
from bot_core.telemetry.targeting import TargetingTelemetry
from adaptive_config import (
    DUEL_MOVEMENT_POLICY,
    ENERGY_DROP_CONFIG,
    FIRE_GATE,
    FIRE_POLICY,
    ADAPTIVE_FORCE_GUN_MODES,
    GUN_POLICY,
    MOVEMENT_POLICY,
    RADAR_CONFIG,
    RADAR_POLICY,
    TARGET_POLICY,
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
        traditional_gf_policy = GUN_POLICY.traditional_gf
        self._gun = VirtualGunSystem(
            standard_runtime_config(
                system=GunSystemConfig(
                    eval_waves_enabled=GUN_POLICY.eval_waves_enabled,
                    eval_wave_min_interval=GUN_POLICY.eval_wave_min_interval,
                ),
                selector=selector_config_from_policy(GUN_POLICY),
                scoring=GunScoringConfig(selectable_modes=GUN_POLICY.selectable_modes),
                min_visits=GUN_POLICY.min_visits,
                min_switch_score=GUN_POLICY.min_switch_score,
                displacement=DisplacementGunConfig(
                    markov_enabled=GUN_POLICY.displacement_markov_enabled,
                    min_switch_visits=GUN_POLICY.displacement_min_switch_visits,
                    min_switch_score=GUN_POLICY.displacement_min_switch_score,
                ),
                dynamic_cluster=dynamic_cluster_config_from_policy(GUN_POLICY),
                traditional_gf=TraditionalGfGunConfig(
                    min_samples=traditional_gf_policy.min_samples,
                    min_switch_visits=traditional_gf_policy.min_switch_visits,
                    min_switch_score=traditional_gf_policy.min_switch_score,
                    global_source_min_switch_visits=traditional_gf_policy.global_source_min_switch_visits,
                    global_source_min_switch_score=traditional_gf_policy.global_source_min_switch_score,
                    trusted_source_min_switch_visits=traditional_gf_policy.trusted_source_min_switch_visits,
                    trusted_source_min_switch_score=traditional_gf_policy.trusted_source_min_switch_score,
                    global_source_centering_factor=traditional_gf_policy.global_source_centering_factor,
                    coarse_source_centering_factor=traditional_gf_policy.coarse_source_centering_factor,
                    coarse_blend_source_centering_factor=traditional_gf_policy.coarse_blend_source_centering_factor,
                    coarse_segment_min_samples=traditional_gf_policy.coarse_segment_min_samples,
                    coarse_segment_full_weight_samples=traditional_gf_policy.coarse_segment_full_weight_samples,
                    peak_selection=traditional_gf_policy.peak_selection,
                ),
                anti_surfer=AntiSurferGunConfig(
                    min_switch_visits=GUN_POLICY.anti_surfer_min_switch_visits,
                    min_switch_score=GUN_POLICY.anti_surfer_min_switch_score,
                ),
            )
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
        self._energy_telemetry = EnergyTelemetry(self._debug)
        self._fire_telemetry = FireTelemetry(self._debug)
        self._movement_telemetry = MovementTelemetry(self._debug)
        self._targeting_telemetry = TargetingTelemetry(self._debug)
        self._debug.log("bot.config", **gun_policy_status_fields(GUN_POLICY, ADAPTIVE_FORCE_GUN_MODES))
        self._fired_bullets = FiredBulletTracker()
        self._last_gun_decision_log_turn: dict[int, int] = {}
        self._last_traditional_gf_profile_log_turn: dict[int, int] = {}

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

    def on_game_started(self, event: GameStartedEvent) -> None:
        self._clear_opponent_learning()
        self._log(
            "battle.reset",
            rounds=event.game_setup.number_of_rounds,
            game_type=event.game_setup.game_type,
        )

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
        self._gun.observe_target(target, self)
        self._log_wave_visits(target)
        if not fire_detected:
            self._record_gun_heat_wave(target)
        if previous is None:
            self._targeting_telemetry.record_scan_new(event.scanned_bot_id, event.energy, event.x, event.y)
        elif previous_age is not None and previous_age > TARGET_POLICY.reacquire_turns:
            self._targeting_telemetry.record_scan_reacquired(event.scanned_bot_id, previous_age, previous, event.x, event.y)

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
        previous_prediction = detection.previous_prediction
        heat_state = detection.heat_state
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
            distance >= FIRE_POLICY.enemy_fire_active_evasion_min_distance
            if not melee_active
            else distance >= FIRE_POLICY.melee_fire_active_evasion_min_distance
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
            inferred_fire_turn=estimated_fire_turn,
            fire_source_x=fire_source.x,
            fire_source_y=fire_source.y,
            fire_source_offset=math.hypot(current_target.x - fire_source.x, current_target.y - fire_source.y),
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
            MOVEMENT_POLICY.field_margin,
            disabled_modes=frozenset() if use_segmented_gun_stats else frozenset({"traditional_gf"}),
            allow_segmented_stats=use_segmented_gun_stats,
        )
        firepower, aim = self._maybe_apply_dynamic_shot_quality_power_scale(
            target,
            distance,
            firepower,
            aim,
            use_segmented_gun_stats,
        )
        score_segment = aim.segment_key if use_segmented_gun_stats else None
        if aim.mode_changed:
            self._fire_telemetry.record_gun_switch(target.bot_id, aim, self._gun.score_summary(target.bot_id, score_segment))
        self._maybe_log_gun_switch_decision(target.bot_id, aim)
        self._maybe_log_traditional_gf_profile(target.bot_id, aim)
        age = self.turn_number - target.seen_turn

        if age > TARGET_POLICY.reacquire_turns:
            if age > TARGET_POLICY.drop_lost_turns:
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
        movement_mode, strafe_offset, flattening = self._set_adaptive_movement(target, distance, body_bearing)

        fire_decision = FIRE_GATE.decide(age, distance, aim.gun_bearing, firepower, self.energy)
        low_energy_override = self._maybe_low_energy_endgame_firepower(target, distance, firepower, aim, fire_decision)
        if low_energy_override is not None:
            override_aim = self._gun.aim(
                self,
                target,
                distance,
                low_energy_override,
                self._target_motion(target),
                MOVEMENT_POLICY.field_margin,
                disabled_modes=frozenset() if use_segmented_gun_stats else frozenset({"traditional_gf"}),
                allow_segmented_stats=use_segmented_gun_stats,
            )
            override_alignment_limit = float(min(
                FIRE_GATE.alignment_limit(distance),
                FIRE_POLICY.low_energy_endgame_alignment_degrees,
            ))
            override_quality = self._dynamic_shot_quality_value(override_aim, "shot_quality", default=-1.0)
            final_reject_reason = None
            if override_aim.mode != "dynamic_cluster":
                final_reject_reason = "final_aim_mode"
            elif override_quality < FIRE_POLICY.low_energy_endgame_min_shot_quality:
                final_reject_reason = "final_shot_quality"
            elif abs(override_aim.gun_bearing) > override_alignment_limit:
                final_reject_reason = "final_alignment"
            elif self.energy <= low_energy_override:
                final_reject_reason = "final_energy"
            if final_reject_reason is None:
                firepower = low_energy_override
                aim = override_aim
                score_segment = aim.segment_key if use_segmented_gun_stats else None
                fire_decision = FireDecision(True, "low_energy_endgame", override_alignment_limit)
                self._record_low_energy_endgame(
                    target,
                    distance,
                    aim,
                    firepower,
                    "final",
                    "accepted",
                    "firing",
                    override_alignment_limit,
                    override_quality,
                    proposed_firepower=low_energy_override,
                )
            else:
                self._record_low_energy_endgame(
                    target,
                    distance,
                    override_aim,
                    firepower,
                    "final",
                    "rejected",
                    final_reject_reason,
                    override_alignment_limit,
                    override_quality,
                    proposed_firepower=low_energy_override,
                )
        self.set_turn_gun_left(aim.gun_bearing)
        if age <= 2 and self.gun_heat <= 0 and self.energy > firepower:
            self._gun.maybe_add_eval_wave(self, target, firepower, aim)
        self._fire_telemetry.sample_track(
            FireTick(
                target=target,
                age=age,
                distance=distance,
                aim=aim,
                radar=radar_command,
                firepower=firepower,
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

    def _maybe_apply_dynamic_shot_quality_power_scale(
        self,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        aim: AimSolution,
        use_segmented_gun_stats: bool,
    ) -> tuple[float, AimSolution]:
        if not FIRE_POLICY.dynamic_shot_quality_power_scaling_enabled:
            return firepower, aim
        if aim.mode != "dynamic_cluster":
            return firepower, aim
        if target.energy <= FIRE_POLICY.finish_target_energy and distance < 320:
            return firepower, aim
        power_scale = self._dynamic_shot_quality_value(aim, "recommended_power_scale", default=1.0)
        adjusted_firepower = max(0.1, min(firepower, firepower * power_scale))
        if abs(adjusted_firepower - firepower) < 0.01:
            return firepower, aim
        adjusted_aim = self._gun.aim(
            self,
            target,
            distance,
            adjusted_firepower,
            self._target_motion(target),
            MOVEMENT_POLICY.field_margin,
            disabled_modes=frozenset() if use_segmented_gun_stats else frozenset({"traditional_gf"}),
            allow_segmented_stats=use_segmented_gun_stats,
        )
        if adjusted_aim.mode != "dynamic_cluster":
            return firepower, aim
        return adjusted_firepower, adjusted_aim

    def _maybe_low_energy_endgame_firepower(
        self,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        aim: AimSolution,
        fire_decision: FireDecision,
    ) -> float | None:
        if not FIRE_POLICY.low_energy_endgame_fire_enabled:
            return None
        if fire_decision.reason != "energy_margin":
            return None
        alignment_limit = float(min(
            FIRE_GATE.alignment_limit(distance),
            FIRE_POLICY.low_energy_endgame_alignment_degrees,
        ))
        shot_quality = self._dynamic_shot_quality_value(aim, "shot_quality", default=-1.0)

        def reject(reason: str) -> None:
            self._record_low_energy_endgame(
                target,
                distance,
                aim,
                firepower,
                "candidate",
                "rejected",
                reason,
                alignment_limit,
                shot_quality,
            )

        if self.energy > FIRE_POLICY.low_energy_endgame_max_energy:
            reject("max_energy")
            return None
        if distance > FIRE_POLICY.low_energy_endgame_max_distance:
            reject("distance")
            return None
        if abs(aim.gun_bearing) > FIRE_POLICY.low_energy_endgame_alignment_degrees:
            reject("alignment")
            return None
        if aim.mode != "dynamic_cluster":
            reject("aim_mode")
            return None
        target_is_finisher = target.energy <= FIRE_POLICY.finish_target_energy
        target_has_lead = target.energy > self.energy
        if not (target_is_finisher or target_has_lead):
            reject("endgame_context")
            return None
        if shot_quality < FIRE_POLICY.low_energy_endgame_min_shot_quality:
            reject("shot_quality")
            return None
        max_firepower = float(self.energy) - FIRE_POLICY.low_energy_endgame_energy_reserve
        if max_firepower < 0.1:
            reject("energy_reserve")
            return None
        proposed_firepower = float(max(0.1, min(firepower, max_firepower)))
        self._record_low_energy_endgame(
            target,
            distance,
            aim,
            firepower,
            "candidate",
            "accepted",
            "eligible",
            alignment_limit,
            shot_quality,
            proposed_firepower=proposed_firepower,
        )
        return proposed_firepower

    def _record_low_energy_endgame(
        self,
        target: TargetSnapshot,
        distance: float,
        aim: AimSolution,
        firepower: float,
        stage: str,
        decision: str,
        reason: str,
        alignment_limit: float,
        shot_quality: float | None,
        *,
        proposed_firepower: float | None = None,
    ) -> None:
        self._fire_telemetry.record_low_energy_endgame(
            target_id=target.bot_id,
            stage=stage,
            decision=decision,
            reason=reason,
            energy=self.energy,
            target_energy=target.energy,
            distance=distance,
            firepower=firepower,
            aim_mode=aim.mode,
            gun_bearing=aim.gun_bearing,
            alignment_limit=alignment_limit,
            shot_quality=shot_quality,
            proposed_firepower=proposed_firepower,
        )

    @staticmethod
    def _dynamic_shot_quality_value(aim: AimSolution, key: str, default: float) -> float:
        diagnostics = aim.gun_diagnostics.get("dynamic_cluster", {})
        if not isinstance(diagnostics, dict):
            return default
        value = diagnostics.get(key)
        return float(value) if isinstance(value, (int, float)) else default

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
                self._movement_telemetry.sample_minimum_risk(
                    target.bot_id,
                    decision,
                    command,
                    len(self._targets),
                    fire_threat_id=threat_target.bot_id if threat_target is not None else None,
                    include_fire_threat=True,
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
                self._movement_telemetry.record_duel_flattening(target.bot_id, flattening, distance, self._evade_direction)
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
                    self._movement_telemetry.sample_goto_surf(target.bot_id, surf_decision, command, self._evade_direction)
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
            self._movement_telemetry.sample_duel_potential(
                target.bot_id,
                destination_x,
                destination_y,
                force_x,
                force_y,
                distance,
                movement_mode,
                evading,
                self._evade_direction,
                command,
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
            if MOVEMENT_POLICY.flattener_active:
                self._movement_telemetry.record_flattening(target.bot_id, flattening, distance, current_direction=self._evade_direction)
            else:
                self._movement_telemetry.record_flattening_shadow(target.bot_id, flattening, distance, self._evade_direction)
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

    @staticmethod
    def _wall_axis_force(distance: float, margin: float) -> float:
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

    @staticmethod
    def _melee_movement_command(
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

        gun_score, gun_visits = self._gun.active_target_confidence(target.bot_id)
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

    def _maybe_log_gun_switch_decision(self, target_id: int, aim: AimSolution) -> None:
        last_turn = self._last_gun_decision_log_turn.get(target_id, -100000)
        if not should_log_switch_decision(aim, self.turn_number, last_turn, GUN_POLICY.switch_diagnostics_interval):
            return
        self._fire_telemetry.record_gun_switch_decision(target_id, aim)
        self._last_gun_decision_log_turn[target_id] = self.turn_number

    def _maybe_log_traditional_gf_profile(self, target_id: int, aim: AimSolution) -> None:
        if aim.gun_diagnostics.get("traditional_gf") is None:
            return
        last_turn = self._last_traditional_gf_profile_log_turn.get(target_id, -100000)
        if not aim.mode_changed and self.turn_number - last_turn < GUN_POLICY.switch_diagnostics_interval:
            return
        self._fire_telemetry.record_traditional_gf_profile(target_id, aim)
        self._last_traditional_gf_profile_log_turn[target_id] = self.turn_number

    def _update_own_motion_stats(self) -> None:
        self._own_motion.update(self)

    def _log_wave_visits(self, target: TargetSnapshot) -> None:
        for visit in self._gun.update_waves(self, target):
            self._fire_telemetry.record_wave_visit(visit)
        for visit in self._gun.update_eval_waves(self, target):
            self._fire_telemetry.record_eval_wave_visit(visit)

    def _log_movement_profile_visits(self) -> None:
        for visit in self._movement.update(self):
            self._movement_telemetry.record_profile_visit(visit)

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

    def _clear_opponent_learning(self) -> None:
        self._targets.clear()
        self._target_id = None
        self._recent_threat_id = None
        self._recent_threat_turn = -1000
        self._evade_until_turn = -1
        self._last_enemy_fire_turn = -1000
        self._enemy_energy_corrections.clear()
        self._last_enemy_power_prediction.clear()
        self._enemy_fire_power.clear()
        self._gun.clear_battle_state()
        self._movement.clear_battle_state()
        self._minimum_risk.clear_round_state()
        self._enemy_gun_heat.clear_round_state()
        self._fired_bullets.clear()
        self._last_gun_decision_log_turn.clear()
        self._last_traditional_gf_profile_log_turn.clear()
        self._target_accel.clear()
        self._last_velocity_change_turn.clear()
        self._own_motion.reset()
        self._melee_round = False
        self._last_turn_number = -1

    def _drop_lost_target(self, target: TargetSnapshot, age: int, distance: float) -> None:
        self._targets.pop(target.bot_id, None)
        self._gun.remove_target(target.bot_id)
        self._movement.remove_target(target.bot_id, clear_profile=False)
        self._enemy_fire_detector.remove_target(target.bot_id)
        if self._target_id == target.bot_id:
            self._target_id = None
        self._search()
        self._targeting_telemetry.record_target_drop_lost(target, age, distance, len(self._targets))

    def _forget_stale_targets(self) -> None:
        stale_ids = self._targets.stale_ids(self.turn_number, TARGET_POLICY.memory_turns)
        for bot_id in stale_ids:
            self._log("target.stale", bot_id=bot_id)
            del self._targets[bot_id]
            self._gun.remove_target(bot_id)
            self._movement.remove_target(bot_id, clear_profile=False)
            self._enemy_fire_detector.remove_target(bot_id)
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
            self._targeting_telemetry.record_target_selection(selection, len(self._targets))
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
            self._movement_telemetry.sample_search_wall_avoid(self.x, self.y, center_bearing, self._evade_direction, self._near_wall())
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
        self._enemy_fire_detector.remove_target(event.victim_id)
        self._enemy_gun_heat.remove_target(event.victim_id)
        self._last_enemy_power_prediction.pop(event.victim_id, None)
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
        self._movement.record_shadow_bullet_state(
            event.bullet.bullet_id,
            event.bullet.x,
            event.bullet.y,
            event.bullet.direction,
            event.bullet.speed,
            self.turn_number,
        )
        bullet_fields = self._fired_bullets.record(
            event.bullet.bullet_id,
            aim_mode=wave.aim_mode if wave is not None else None,
            aim_guess_factor=round(wave.aim_guess_factor, 3)
            if wave is not None and wave.aim_guess_factor is not None
            else None,
            traditional_gf_source=getattr(wave.gun_metadata.get("traditional_gf"), "source", None)
            if wave is not None and wave.aim_mode == "traditional_gf"
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
            shadow_bullets=self._movement.shadow_bullet_count,
            selected_gun_confidence=selected_gun_score,
            selected_gun_confidence_visits=selected_gun_visits,
        )
        if wave is not None:
            self._fire_telemetry.record_fire_drift(
                event.bullet.bullet_id,
                target_id,
                wave.aim_mode,
                wave.source_x,
                wave.source_y,
                wave.virtual_bearings.get(wave.aim_mode, wave.fire_bearing),
                wave.bullet_power,
                wave.bullet_speed,
                event.bullet.x,
                event.bullet.y,
                event.bullet.direction,
                event.bullet.power,
                event.bullet.speed,
            )

    def _log(self, event: str, **fields: object) -> None:
        self._debug.log(event, **fields)

if __name__ == "__main__":
    AdaptivePrime().start()
