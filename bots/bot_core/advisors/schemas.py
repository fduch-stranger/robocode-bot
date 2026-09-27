"""Typed advisor questions (Jev System One ``choice`` questions) and answer parsing."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

STYLE_QUESTION_ID = "enemy_style"
SURF_QUESTION_ID = "surf_side"

STYLE_OPTIONS: dict[str, str] = {
    "wave_surfer": (
        "Moves mostly sideways to us and changes direction in reaction to our shots, "
        "dodging bullets that are already in the air."
    ),
    "orbiter": (
        "Circles us at a steady distance, moving sideways at a steady speed; its direction "
        "changes are not tied to our shots."
    ),
    "chaser": (
        "Presses in toward us and holds a close or medium range band, keeping pressure on us; "
        "it may ram."
    ),
    "sweeper": (
        "Drives in wide sweeping arcs across the field, so its distance to us swings a lot, "
        "turning away from walls."
    ),
    "oscillator": "Moves back and forth on a short, regular rhythm that does not depend on our shots.",
    "linear_mover": "Drives in long straight lines at a steady speed and turns mainly at walls.",
    "random_mover": "Changes speed and direction often, at irregular moments not linked to our shots.",
    "stationary": "Stays still or nearly still.",
}

STYLE_INSTRUCTIONS = (
    "Which description best matches how `enemy` moves, based only on the observations of it in "
    "the state?"
)

SURF_OPTIONS: dict[str, str] = {
    "forward": (
        "Keep moving sideways in our current direction at full speed, ending up well ahead of "
        "where we are now."
    ),
    "reverse": (
        "Move sideways in the opposite direction at full speed, ending up behind where we are now."
    ),
    "stop": "Stay close to where we are now.",
}

SURF_INSTRUCTIONS = (
    "The enemy has just fired `incoming_bullet` at us. The enemy aims where it has hit us "
    "before, which `recent_hits_on_us` describes. Which movement makes `incoming_bullet` most "
    "likely to miss us?"
)


def choice_question(instructions: str, options: Mapping[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def style_questions() -> dict[str, dict[str, Any]]:
    return {STYLE_QUESTION_ID: choice_question(STYLE_INSTRUCTIONS, STYLE_OPTIONS)}


def surf_questions() -> dict[str, dict[str, Any]]:
    return {SURF_QUESTION_ID: choice_question(SURF_INSTRUCTIONS, SURF_OPTIONS)}


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float

    def probability(self, option: str) -> float:
        return self.probabilities.get(option, 0.0)


def parse_choice(answer: object, options: Mapping[str, str]) -> ChoiceAnswer | None:
    """Validate one ``choice`` answer; returns None when it is malformed or names an unknown option."""
    if not isinstance(answer, Mapping) or answer.get("type") != "choice":
        return None
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice not in options:
        return None
    raw_probabilities = answer.get("probabilities")
    probabilities: dict[str, float] = {}
    if isinstance(raw_probabilities, Mapping):
        for option, value in raw_probabilities.items():
            if option in options and isinstance(value, (int, float)):
                probabilities[str(option)] = float(value)
    confidence = answer.get("confidence")
    return ChoiceAnswer(
        choice=choice,
        probabilities=probabilities,
        confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
    )
