"""Adaptive Jev's advisor layer: builds questions from game state, submits them, and logs answers.

Every entry point is guarded, so a bug here is logged as ``advisor.error`` and the bot keeps playing
exactly as Adaptive Prime would.
"""
from __future__ import annotations

from collections.abc import Callable

from robocode_tank_royale.bot_api import Bot

from bot_core.advisors.client import SUBMIT_QUEUED, AdvisorClient, AdvisorRequest, AdvisorResult
from bot_core.advisors.jev_transport import JevTransport
from bot_core.advisors.observers import (
    EnemyStyleObserver,
    SurfObserver,
    SurfRecord,
    outcome_option,
    wave_surf_features,
)
from bot_core.advisors.schemas import (
    STYLE_OPTIONS,
    STYLE_QUESTION_ID,
    SURF_OPTIONS,
    SURF_QUESTION_ID,
    parse_choice,
    style_questions,
    surf_questions,
)
from bot_core.advisors.state_summary import rule_based_style, style_state, surf_state
from bot_core.advisors.stub_transport import StubTransport
from bot_core.movement import MovementWave
from bot_core.telemetry.advisor import AdvisorTelemetry
from jev_config import JevConfig

MAX_LOGGED_INTERNAL_ERRORS = 20
LINEAR_AIM_MIN_VISITS = 20
STYLE_RETRY_SAMPLES = 10


def build_transport(config: JevConfig):
    """The configured transport, or None when the Jev transport has no API key."""
    if config.transport == "stub":
        return StubTransport(mode=config.stub_mode, latency_ms=config.stub_latency_ms)
    return JevTransport.from_environment()


class JevAdvisorLayer:
    def __init__(
        self,
        bot: Bot,
        config: JevConfig,
        client: AdvisorClient,
        telemetry: AdvisorTelemetry,
        linear_aim_hit_rate: Callable[[int], float | None] | None = None,
    ) -> None:
        self._bot = bot
        self._config = config
        self._client = client
        self._telemetry = telemetry
        self._linear_aim_hit_rate = linear_aim_hit_rate or (lambda _target_id: None)
        self._style_observers: dict[int, EnemyStyleObserver] = {}
        self._next_style_samples: dict[int, int] = {}
        self._surf = SurfObserver()
        self._internal_errors = 0
        self._closed = False

    # Game inputs.

    def on_scan(self, bot_id: int, x: float, y: float, direction: float, speed: float) -> None:
        try:
            bot = self._bot
            if bot.enemy_count > 1:
                return
            observer = self._style_observers.setdefault(bot_id, EnemyStyleObserver())
            observer.observe_scan(
                bot.round_number,
                bot.turn_number,
                bot.x,
                bot.y,
                x,
                y,
                direction,
                speed,
                bot.arena_width,
                bot.arena_height,
            )
        except Exception as error:  # noqa: BLE001
            self.on_listener_error(error)

    def on_bullet_fired(self, target_id: int, distance: float, bullet_speed: float) -> None:
        try:
            observer = self._style_observers.get(target_id)
            if observer is not None:
                observer.observe_our_shot(self._bot.round_number, self._bot.turn_number, distance, bullet_speed)
        except Exception as error:  # noqa: BLE001
            self.on_listener_error(error)

    def on_collision(self, bot_id: int) -> None:
        try:
            observer = self._style_observers.get(bot_id)
            if observer is not None:
                observer.observe_collision()
        except Exception as error:  # noqa: BLE001
            self.on_listener_error(error)

    def on_turn_end(self) -> None:
        try:
            self._drain()
            if self._config.phase_enabled("style"):
                self._maybe_ask_style()
        except Exception as error:  # noqa: BLE001
            self.on_listener_error(error)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._telemetry.record_stats(**self._client.stats(), internal_errors=self._internal_errors)
        finally:
            self._client.close()

    # MovementWaveListener.

    def on_enemy_wave(self, bot: Bot, wave: MovementWave) -> None:
        if not self._config.phase_enabled("surf") or wave.kind != "confirmed" or bot.enemy_count > 1:
            return
        features = wave_surf_features(
            bot.x,
            bot.y,
            bot.direction,
            bot.speed,
            wave.source_x,
            wave.source_y,
            wave.bullet_speed,
            wave.max_escape_angle_positive,
            wave.max_escape_angle_negative,
            self._surf.recent_hit_guess_factors,
        )
        key = self._surf_key(bot.round_number, wave)
        context = {"target": wave.target_id, "fired_turn": wave.fired_turn}
        request = AdvisorRequest("surf", key, bot.turn_number, surf_state(features), surf_questions(), context)
        submit = self._client.submit(request)
        if submit == SUBMIT_QUEUED:
            self._surf.track(SurfRecord(key, bot.turn_number, context=context))
        self._telemetry.record_request("surf", key, bot.turn_number, submit, **context)

    def on_wave_visit(self, bot: Bot, wave: MovementWave, guess_factor: float, hit: bool) -> None:
        if wave.kind != "confirmed":
            return
        record = self._surf.record_visit(self._surf_key(bot.round_number, wave), bot.turn_number, guess_factor, hit)
        if record is not None:
            self._log_outcome(record)

    def on_round_cleared(self) -> None:
        return None

    def on_listener_error(self, error: Exception) -> None:
        self._internal_errors += 1
        if self._internal_errors <= MAX_LOGGED_INTERNAL_ERRORS:
            try:
                self._telemetry.record_error("internal", "-", f"exception:{type(error).__name__}")
            except Exception:  # noqa: BLE001
                pass

    # Internals.

    @staticmethod
    def _surf_key(round_number: int, wave: MovementWave) -> str:
        return f"surf:r{round_number}:t{wave.target_id}:f{wave.fired_turn}"

    def _maybe_ask_style(self) -> None:
        bot = self._bot
        if bot.enemy_count > 1:
            return
        for target_id, observer in self._style_observers.items():
            threshold = self._next_style_samples.get(target_id, self._config.style_first_samples)
            if observer.samples < threshold:
                continue
            features = observer.features(self._linear_aim_hit_rate(target_id))
            key = f"style:r{bot.round_number}:t{target_id}:s{observer.samples}"
            context = {"target": target_id, "samples": observer.samples, "rule": rule_based_style(features)}
            state = style_state(features)
            request = AdvisorRequest("style", key, bot.turn_number, state, style_questions(), context)
            submit = self._client.submit(request)
            # A rate-limited question is retried soon instead of waiting a full interval.
            delay = self._config.style_interval_samples if submit == SUBMIT_QUEUED else STYLE_RETRY_SAMPLES
            self._next_style_samples[target_id] = observer.samples + delay
            self._telemetry.record_request("style", key, bot.turn_number, submit, summary=state["enemy"], **context)

    def _drain(self) -> None:
        for result in self._client.drain():
            self._handle_result(result)

    def _handle_result(self, result: AdvisorResult) -> None:
        request = result.request
        turn = self._bot.turn_number
        if not result.ok:
            self._telemetry.record_error(request.kind, str(request.key), result.error or "unknown", result.status, result.latency_ms)
            if request.kind == "surf":
                self._surf.forget(str(request.key))
            return
        question_id, options = (
            (STYLE_QUESTION_ID, STYLE_OPTIONS) if request.kind == "style" else (SURF_QUESTION_ID, SURF_OPTIONS)
        )
        answer = parse_choice((result.answers or {}).get(question_id), options)
        if answer is None:
            self._telemetry.record_error(request.kind, str(request.key), "parse", None, result.latency_ms)
            if request.kind == "surf":
                self._surf.forget(str(request.key))
            return
        self._telemetry.record_answer(
            request.kind,
            str(request.key),
            request.request_turn,
            turn,
            result.latency_ms,
            result.model,
            result.input_tokens,
            answer.choice,
            answer.confidence,
            answer.probabilities,
            "shadow",
            **request.context,
        )
        if request.kind == "surf":
            record = self._surf.record_answer(str(request.key), answer.choice, answer.confidence, turn)
            if record is not None:
                self._log_outcome(record)

    def _log_outcome(self, record: SurfRecord) -> None:
        if record.answer_turn is None or record.visit_turn is None or record.guess_factor is None:
            return
        self._telemetry.record_outcome(
            record.key,
            record.request_turn,
            record.answer_turn,
            record.visit_turn,
            record.answer,
            record.confidence,
            outcome_option(record.guess_factor),
            record.guess_factor,
            bool(record.hit),
            **record.context,
        )
