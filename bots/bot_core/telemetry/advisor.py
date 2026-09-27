"""Telemetry for the asynchronous advisor layer (advisor.* events)."""
from __future__ import annotations

from collections.abc import Mapping

from bot_core.telemetry.sink import TelemetrySink


def _rounded(probabilities: Mapping[str, float]) -> dict[str, float]:
    return {option: round(value, 3) for option, value in probabilities.items()}


class AdvisorTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def record_config(self, **fields: object) -> None:
        self._sink.log("advisor.config", **fields)

    def record_request(self, kind: str, key: str, request_turn: int, submit: str, **context: object) -> None:
        self._sink.log("advisor.request", kind=kind, key=key, request_turn=request_turn, submit=submit, **context)

    def record_answer(
        self,
        kind: str,
        key: str,
        request_turn: int,
        answer_turn: int,
        latency_ms: float,
        model: str | None,
        input_tokens: int | None,
        choice: str,
        confidence: float,
        probabilities: Mapping[str, float],
        status: str,
        **context: object,
    ) -> None:
        self._sink.log(
            "advisor.answer",
            kind=kind,
            key=key,
            request_turn=request_turn,
            answer_turn=answer_turn,
            latency_ms=round(latency_ms, 1),
            latency_turns=answer_turn - request_turn,
            model=model,
            input_tokens=input_tokens,
            choice=choice,
            confidence=round(confidence, 3),
            probabilities=_rounded(probabilities),
            status=status,
            **context,
        )

    def record_error(
        self,
        kind: str,
        key: str,
        error: str,
        status: int | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self._sink.log(
            "advisor.error",
            kind=kind,
            key=key,
            error=error,
            http_status=status,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
        )

    def record_outcome(
        self,
        key: str,
        request_turn: int,
        answer_turn: int,
        visit_turn: int,
        answer: str | None,
        confidence: float | None,
        realized: str,
        guess_factor: float,
        hit: bool,
        **context: object,
    ) -> None:
        self._sink.log(
            "advisor.outcome",
            kind="surf",
            key=key,
            request_turn=request_turn,
            answer_turn=answer_turn,
            visit_turn=visit_turn,
            answered_before_visit=answer_turn <= visit_turn,
            answer=answer,
            confidence=round(confidence, 3) if confidence is not None else None,
            realized=realized,
            guess_factor=round(guess_factor, 3),
            hit=hit,
            **context,
        )

    def record_stats(self, **fields: object) -> None:
        self._sink.log("advisor.stats", **fields)
