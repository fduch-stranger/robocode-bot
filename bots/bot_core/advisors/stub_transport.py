"""Offline advisor transport: fixed or random ``choice`` answers with simulated latency."""
from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

from bot_core.advisors.jev_transport import TransportResponse

STUB_MODES = ("fixed", "random")


class StubTransport:
    name = "stub"

    def __init__(
        self,
        *,
        mode: str = "random",
        fixed_choices: Mapping[str, str] | None = None,
        seed: int | None = None,
        latency_ms: float = 0.0,
    ) -> None:
        if mode not in STUB_MODES:
            raise ValueError(f"stub mode must be one of {STUB_MODES}")
        self.mode = mode
        self._fixed_choices = dict(fixed_choices or {})
        self._random = random.Random(seed)
        self._latency_s = max(0.0, latency_ms / 1000.0)

    def evaluate(self, state: object, questions: Mapping[str, Mapping[str, Any]]) -> TransportResponse:
        if self._latency_s:
            time.sleep(self._latency_s)
        answers: dict[str, Any] = {}
        for question_id, question in questions.items():
            options = list(question.get("criteria") or {})
            if not options:
                continue
            if self.mode == "fixed":
                choice = self._fixed_choices.get(question_id)
                if choice not in options:
                    choice = options[0]
                probabilities = {option: 1.0 if option == choice else 0.0 for option in options}
            else:
                weights = [self._random.random() for _ in options]
                total = sum(weights) or 1.0
                probabilities = {option: weight / total for option, weight in zip(options, weights)}
                choice = max(probabilities, key=probabilities.__getitem__)
            answers[question_id] = {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities,
                "confidence": probabilities[choice],
            }
        return TransportResponse(answers=answers, model=f"stub-{self.mode}", input_tokens=0)
