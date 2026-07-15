from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.angles import absolute_bearing_between, relative_bearing
from bot_core.geometry.waves import guess_factor_from_offset, wall_limited_escape_angle
from bot_core.gun.aim import AimModeSelector
from bot_core.gun.config import GunDecisionContext, GunRuntimeConfig, GunScoringConfig, GunSelectorConfig, GunSystemConfig
from bot_core.gun.context import (
    AimContext,
    GunBearing,
    GunVisit,
    TargetHistoryStore,
    build_fire_context,
    build_gun_features,
    movement_context_tags,
)
from bot_core.gun.models import (
    AimSolution,
    GunStats,
    GunSwitchCandidate,
    GunWave,
    TargetMotion,
    WaveVisit,
)
from bot_core.gun.registry import GunRegistry
from bot_core.gun.scoring import VirtualGunScorer
from bot_core.gun.features import segment_features
from bot_core.gun.kinematics import lateral_direction, point_on_bearing
from bot_core.gun.waves import GunWaveTracker
from bot_core.physics import bullet_speed_for_power
from bot_core.target_snapshot import TargetSnapshot


@dataclass
class VirtualGunSystem:
    config: GunRuntimeConfig
    _waves: list[GunWave] = field(default_factory=list)
    _eval_waves: list[GunWave] = field(default_factory=list)
    _stats: dict[tuple[int, str], GunStats] = field(default_factory=dict)
    _segment_stats: dict[tuple[int, str, tuple[int, ...]], GunStats] = field(default_factory=dict)
    _eval_stats: dict[tuple[int, str], GunStats] = field(default_factory=dict)
    _eval_segment_stats: dict[tuple[int, str, tuple[int, ...]], GunStats] = field(default_factory=dict)
    _active_modes: dict[int, str] = field(default_factory=dict)
    _wave_tracker: GunWaveTracker = field(init=False)
    _scorer: VirtualGunScorer = field(init=False)
    _eval_scorer: VirtualGunScorer = field(init=False)
    _aim_selector: AimModeSelector = field(init=False)
    _system_config: GunSystemConfig = field(init=False)
    _scoring_config: GunScoringConfig = field(init=False)
    _selector_config: GunSelectorConfig = field(init=False)
    _target_history_store: TargetHistoryStore = field(init=False)
    _registry: GunRegistry = field(init=False)
    _last_eval_wave_turn: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        runtime_config = self.config
        self.config = runtime_config
        self._system_config = runtime_config.system
        self._scoring_config = runtime_config.scoring
        self._selector_config = runtime_config.selector
        self._target_history_store = TargetHistoryStore(self._system_config.max_target_history)
        self._registry = GunRegistry(runtime_config.component_factory(self._target_history_store))
        self._wave_tracker = GunWaveTracker(self._system_config, self._waves)
        self._scorer = VirtualGunScorer(self._scoring_config, self._stats, self._segment_stats)
        self._eval_scorer = VirtualGunScorer(self._scoring_config, self._eval_stats, self._eval_segment_stats)
        self._aim_selector = AimModeSelector(
            self._selector_config,
            self._scorer,
            self._active_modes,
            self._stats,
            self._registry.mode_policies,
            self._eval_scorer,
        )

    @property
    def sample_count(self) -> int:
        return int(self._registry.metric("sample_count"))

    @property
    def wave_count(self) -> int:
        return len(self._waves)

    @property
    def eval_wave_count(self) -> int:
        return len(self._eval_waves)

    def observe_target(self, target: TargetSnapshot, bot: Bot | None = None) -> None:
        self._target_history_store.observe_target(target, bot)

    def aim(
        self,
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        motion: TargetMotion,
        field_margin: float,
        disabled_modes: frozenset[str] | None = None,
        allow_segmented_stats: bool = True,
    ) -> AimSolution:
        context = self._aim_context(bot, target, distance, firepower, motion, field_margin, disabled_modes)
        scoring_segment = context.segment_key if allow_segmented_stats else None
        bearings = self._registry.bearings(context)
        virtual_bearings = {mode: bearing.absolute_bearing for mode, bearing in bearings.items()}
        decision_contexts = {
            mode: bearing.decision_context
            for mode, bearing in bearings.items()
            if bearing.decision_context is not None
        }
        mode, previous_mode, mode_changed, switch_candidates = self._select_aim_mode(
            target.bot_id,
            virtual_bearings,
            scoring_segment,
            decision_contexts,
        )
        return self._aim_solution(
            bot,
            distance,
            field_margin,
            context,
            bearings,
            mode,
            previous_mode,
            mode_changed,
            switch_candidates,
        )

    def reaim_selected_mode(
        self,
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        motion: TargetMotion,
        field_margin: float,
        selection: AimSolution,
        disabled_modes: frozenset[str] | None = None,
    ) -> AimSolution:
        """Recompute the selected gun at new shot inputs without running the selector."""
        context = self._aim_context(bot, target, distance, firepower, motion, field_margin, disabled_modes)
        bearings = self._registry.bearings(context)
        if selection.mode not in bearings:
            raise ValueError(f"Selected gun {selection.mode!r} is unavailable during re-aim")
        return self._aim_solution(
            bot,
            distance,
            field_margin,
            context,
            bearings,
            selection.mode,
            selection.previous_mode,
            selection.mode_changed,
            selection.switch_candidates,
        )

    def _aim_solution(
        self,
        bot: Bot,
        distance: float,
        field_margin: float,
        context: AimContext,
        bearings: dict[str, GunBearing],
        mode: str,
        previous_mode: str | None,
        mode_changed: bool,
        switch_candidates: tuple[GunSwitchCandidate, ...],
    ) -> AimSolution:
        virtual_bearings = {bearing_mode: bearing.absolute_bearing for bearing_mode, bearing in bearings.items()}
        gun_diagnostics = self._gun_diagnostics_from_bearings(bearings)
        aim_bearing = virtual_bearings[mode]
        predicted_x, predicted_y = point_on_bearing(bot, aim_bearing, distance, field_margin)
        return AimSolution(
            predicted_x=predicted_x,
            predicted_y=predicted_y,
            gun_bearing=relative_bearing(aim_bearing, bot.gun_direction),
            mode=mode,
            guess_factor=bearings[mode].guess_factor,
            features=context.features,
            segment_key=context.segment_key,
            virtual_bearings=virtual_bearings,
            fire_context=context.fire_context,
            previous_mode=previous_mode,
            mode_changed=mode_changed,
            switch_candidates=switch_candidates,
            gun_diagnostics=gun_diagnostics,
        )

    @staticmethod
    def make_wave(
        bot: Bot,
        target: TargetSnapshot,
        firepower: float,
        aim: AimSolution,
    ) -> GunWave:
        bullet_speed = bullet_speed_for_power(firepower)
        fire_bearing = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
        wave_lateral_direction = lateral_direction(target, fire_bearing)
        positive_escape_angle = aim.fire_context.positive_escape_angle or wall_limited_escape_angle(
            bot,
            target,
            bullet_speed,
            wave_lateral_direction,
        )
        negative_escape_angle = aim.fire_context.negative_escape_angle or wall_limited_escape_angle(
            bot,
            target,
            bullet_speed,
            -wave_lateral_direction,
        )
        return GunWave(
            source_x=bot.x,
            source_y=bot.y,
            fire_turn=bot.turn_number,
            fire_bearing=fire_bearing,
            target_id=target.bot_id,
            bullet_power=firepower,
            bullet_speed=bullet_speed,
            max_escape_angle_positive=positive_escape_angle,
            max_escape_angle_negative=negative_escape_angle,
            lateral_direction=wave_lateral_direction,
            features=aim.features,
            segment_key=aim.segment_key,
            aim_mode=aim.mode,
            aim_guess_factor=aim.guess_factor,
            virtual_bearings=aim.virtual_bearings,
            fire_context=aim.fire_context,
            gun_metadata=aim.gun_diagnostics,
        )

    def set_pending_wave(self, wave: GunWave) -> None:
        self._wave_tracker.set_pending_wave(wave)

    def record_pending_fire(self) -> GunWave | None:
        return self._wave_tracker.record_pending_fire()

    def maybe_add_eval_wave(self, bot: Bot, target: TargetSnapshot, firepower: float, aim: AimSolution) -> bool:
        if not self._system_config.eval_waves_enabled:
            return False
        last_turn = self._last_eval_wave_turn.get(target.bot_id)
        if last_turn is not None and bot.turn_number - last_turn < self._system_config.eval_wave_min_interval:
            return False
        wave = self.make_wave(bot, target, firepower, aim)
        self._eval_waves.append(wave)
        self._last_eval_wave_turn[target.bot_id] = bot.turn_number
        while len(self._eval_waves) > self._system_config.max_eval_waves:
            self._eval_waves.pop(0)
        return True

    def update_waves(self, bot: Bot, target: TargetSnapshot) -> list[WaveVisit]:
        visits: list[WaveVisit] = []
        remaining_waves: list[GunWave] = []
        for wave in self._wave_tracker.waves:
            resolved = self._resolved_wave_visit(bot, target, wave)
            if resolved is None:
                remaining_waves.append(wave)
                continue
            visits.append(self._record_resolved_visit(target, wave, resolved, is_evaluation=False))

        self._wave_tracker.replace(remaining_waves)
        return visits

    def update_eval_waves(self, bot: Bot, target: TargetSnapshot) -> list[WaveVisit]:
        visits: list[WaveVisit] = []
        remaining_waves: list[GunWave] = []
        for wave in self._eval_waves:
            resolved = self._resolved_wave_visit(bot, target, wave)
            if resolved is None:
                remaining_waves.append(wave)
                continue
            visits.append(self._record_resolved_visit(target, wave, resolved, is_evaluation=True))

        self._eval_waves = remaining_waves
        return visits

    def score_summary(self, target_id: int, segment_key: tuple[int, ...] | None = None) -> dict[str, str]:
        return self._scorer.score_summary(target_id, segment_key)

    def eval_score_summary(self, target_id: int, segment_key: tuple[int, ...] | None = None) -> dict[str, str]:
        return self._eval_scorer.score_summary(target_id, segment_key)

    def target_confidence(self, target_id: int) -> tuple[float, int]:
        return self._scorer.target_confidence(target_id)

    def active_target_confidence(
        self,
        target_id: int,
        segment_key: tuple[int, ...] | None = None,
    ) -> tuple[float, int]:
        return self._scorer.mode_confidence(target_id, self._active_modes.get(target_id), segment_key)

    def mode_confidence(
        self,
        target_id: int,
        mode: str | None,
        segment_key: tuple[int, ...] | None = None,
    ) -> tuple[float, int]:
        return self._scorer.mode_confidence(target_id, mode, segment_key)

    def clear_round_state(self) -> None:
        self._wave_tracker.clear_round_state()
        self._eval_waves.clear()
        self._last_eval_wave_turn.clear()
        self._target_history_store.clear_round_state()
        self._registry.clear_round_state()

    def clear_battle_state(self) -> None:
        self._waves.clear()
        self._eval_waves.clear()
        self._stats.clear()
        self._segment_stats.clear()
        self._eval_stats.clear()
        self._eval_segment_stats.clear()
        self._active_modes.clear()
        self._last_eval_wave_turn.clear()
        self.__post_init__()

    def remove_target(self, target_id: int, *, preserve_pending: bool = False) -> None:
        self._wave_tracker.remove_target(target_id, preserve_pending=preserve_pending)
        self._eval_waves = [wave for wave in self._eval_waves if wave.target_id != target_id]
        self._last_eval_wave_turn.pop(target_id, None)
        self._active_modes.pop(target_id, None)
        self._target_history_store.remove_target(target_id)
        self._registry.remove_target(target_id)

    def _aim_context(
        self,
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        motion: TargetMotion,
        field_margin: float,
        disabled_modes: frozenset[str] | None,
    ) -> AimContext:
        features = build_gun_features(bot, target, distance, firepower, motion)
        history = self._target_history_store.history_for(target.bot_id)
        movement_tags = movement_context_tags(bot, target, features, history)
        fire_context = build_fire_context(bot, target, distance, firepower, features, movement_tags)
        return AimContext(
            bot=bot,
            target=target,
            distance=distance,
            firepower=firepower,
            motion=motion,
            field_margin=field_margin,
            features=features,
            segment_key=segment_features(features),
            disabled_modes=disabled_modes or frozenset(),
            movement_tags=movement_tags,
            fire_context=fire_context,
        )

    @staticmethod
    def _gun_diagnostics_from_bearings(
        bearings: dict[str, object],
    ) -> dict[str, object]:
        metadata: dict[str, object] = {}
        for bearing in bearings.values():
            bearing_metadata = getattr(bearing, "metadata", None)
            if isinstance(bearing_metadata, dict):
                metadata.update(bearing_metadata)
        return metadata

    def _resolved_wave_visit(
        self,
        bot: Bot,
        target: TargetSnapshot,
        wave: GunWave,
    ) -> tuple[float, float, float, float, float, float] | None:
        if wave.target_id != target.bot_id:
            return None
        visit_x, visit_y, traveled, target_distance = self._target_history_store.wave_visit_position(
            bot,
            wave,
            target,
            self._system_config.wave_visit_margin,
        )
        if traveled + self._system_config.wave_visit_margin < target_distance:
            return None

        actual_bearing = absolute_bearing_between(wave.source_x, wave.source_y, visit_x, visit_y)
        bearing_offset = relative_bearing(actual_bearing, wave.fire_bearing)
        guess_factor = guess_factor_from_offset(
            bearing_offset,
            wave.lateral_direction,
            wave.max_escape_angle_positive,
            wave.max_escape_angle_negative,
        )
        return visit_x, visit_y, traveled, target_distance, actual_bearing, guess_factor

    def _record_resolved_visit(
        self,
        target: TargetSnapshot,
        wave: GunWave,
        resolved: tuple[float, float, float, float, float, float],
        is_evaluation: bool,
    ) -> WaveVisit:
        _, _, traveled, target_distance, actual_bearing, guess_factor = resolved
        scorer = self._eval_scorer if is_evaluation else self._scorer
        virtual_scores = scorer.score_virtual_guns(wave, actual_bearing, target_distance)
        visit = GunVisit(
            wave=wave,
            actual_bearing=actual_bearing,
            target_distance=target_distance,
            guess_factor=guess_factor,
            segment_key=wave.segment_key,
            is_evaluation=is_evaluation,
        )
        gun_diagnostics = self._registry.visit_diagnostics(visit)
        self._registry.observe_visit(visit)
        samples = (
            self._eval_target_visits(target.bot_id)
            if is_evaluation
            else int(self._registry.metric("target_sample_count", target.bot_id))
        )
        gun_scores = (
            self.eval_score_summary(target.bot_id, wave.segment_key)
            if is_evaluation
            else self.score_summary(target.bot_id, wave.segment_key)
        )
        return WaveVisit(
            target_id=target.bot_id,
            guess_factor=guess_factor,
            samples=samples,
            traveled=traveled,
            distance=target_distance,
            selected_gun=wave.aim_mode,
            virtual_scores=virtual_scores,
            gun_scores=gun_scores,
            fire_context=wave.fire_context,
            gun_diagnostics=gun_diagnostics,
        )

    def _eval_target_visits(self, target_id: int) -> int:
        return max((stats.visits for (stats_target, _), stats in self._eval_stats.items() if stats_target == target_id), default=0)

    def _select_aim_mode(
        self,
        target_id: int,
        virtual_bearings: dict[str, float],
        segment_key: tuple[int, ...] | None,
        decision_contexts: dict[str, GunDecisionContext],
    ) -> tuple[str, str | None, bool, tuple[GunSwitchCandidate, ...]]:
        return self._aim_selector.select_with_diagnostics(target_id, virtual_bearings, segment_key, decision_contexts)
