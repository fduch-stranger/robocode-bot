"""Game state -> advisor state.

Jev reads text, not numbers, so all arithmetic stays here: every numeric feature is reduced to a
named bucket before it is sent. The rule-based style classifier uses the same features and is the
baseline an advisor answer has to beat.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

STYLE_MIN_OBSERVED_TURNS = 120
HIT_REGIONS = ("far ahead", "slightly ahead", "where we were", "slightly behind", "far behind")


def bucket(value: float, edges: Sequence[tuple[float, str]], top: str) -> str:
    """Name for ``value``: the first ``(limit, name)`` with ``value < limit``, else ``top``."""
    for limit, name in edges:
        if value < limit:
            return name
    return top


@dataclass(frozen=True)
class StyleFeatures:
    observed_turns: int
    mean_speed: float
    mean_lateral_speed: float
    reversals_per_100_turns: float
    # Observed share of reversals near one of our waves passing the enemy, over the chance share.
    reversal_shot_lift: float | None
    mean_distance: float
    distance_spread: float
    distance_trend_per_100_turns: float
    mean_turn_rate: float
    rams_per_round: float
    wall_time_share: float
    linear_aim_hit_rate: float | None

    @property
    def lateral_share(self) -> float:
        return self.mean_lateral_speed / self.mean_speed if self.mean_speed > 1e-9 else 0.0


def style_state(features: StyleFeatures) -> dict[str, Any]:
    lift = features.reversal_shot_lift
    hit_rate = features.linear_aim_hit_rate
    enemy = {
        "speed": bucket(features.mean_speed, ((0.5, "stopped"), (3.0, "slow"), (6.5, "medium")), "full speed"),
        "movement_direction": bucket(
            features.lateral_share,
            ((0.4, "mostly toward or away from us"), (0.75, "mixed")),
            "mostly sideways to us",
        ),
        "direction_changes": bucket(
            features.reversals_per_100_turns,
            ((0.5, "almost never"), (2.0, "rarely"), (5.0, "sometimes"), (10.0, "often")),
            "constantly",
        ),
        "direction_changes_vs_our_shots": (
            "unknown"
            if lift is None
            else bucket(lift, ((1.3, "not tied to our shots"), (2.0, "somewhat tied to our shots")), "strongly tied to our shots")
        ),
        "distance_to_us": bucket(features.mean_distance, ((150.0, "very close"), (300.0, "close"), (500.0, "medium")), "far"),
        "distance_swings": bucket(features.distance_spread, ((40.0, "barely"), (100.0, "somewhat")), "a lot"),
        "distance_trend": bucket(
            features.distance_trend_per_100_turns,
            ((-60.0, "closing in fast"), (-15.0, "closing in"), (15.0, "steady"), (60.0, "backing away")),
            "backing away fast",
        ),
        "turning": bucket(
            features.mean_turn_rate,
            ((0.5, "drives straight"), (2.5, "curves gently"), (6.0, "turns steadily")),
            "turns sharply",
        ),
        "rams_us": bucket(features.rams_per_round, ((0.05, "never"), (1.0, "occasionally"), (3.0, "often")), "constantly"),
        "time_near_walls": bucket(features.wall_time_share, ((0.1, "rarely"), (0.35, "sometimes")), "often"),
        "straight_line_aim_hits_it": (
            "unknown" if hit_rate is None else bucket(hit_rate, ((0.08, "rarely"), (0.2, "sometimes")), "often")
        ),
    }
    observed_for = bucket(features.observed_turns, ((300, "a short time"), (1500, "a while")), "a long time")
    return {"enemy": enemy, "observed_for": observed_for}


def rule_based_style(features: StyleFeatures) -> str:
    """Fixed a-priori rules over the same features Jev sees; the Phase 1 baseline."""
    if features.mean_speed < 0.5:
        return "stationary"
    lateral_share = features.lateral_share
    if features.rams_per_round >= 1.0 or (features.mean_distance < 300.0 and lateral_share < 0.6):
        return "chaser"
    if features.reversal_shot_lift is not None and features.reversal_shot_lift >= 2.0:
        return "wave_surfer"
    if features.mean_turn_rate < 0.5 and features.reversals_per_100_turns < 2.0:
        return "linear_mover"
    if features.reversals_per_100_turns >= 5.0 and features.mean_turn_rate < 1.0:
        return "oscillator"
    if features.distance_spread >= 100.0 and lateral_share < 0.75:
        return "sweeper"
    if lateral_share >= 0.75 and features.distance_spread < 100.0 and features.reversals_per_100_turns < 5.0:
        return "orbiter"
    return "random_mover"


@dataclass(frozen=True)
class SurfFeatures:
    distance: float
    bullet_power: float
    flight_turns: float
    own_speed: float
    own_lateral_share: float
    # Wall-limited escape room in each direction, as a share of the open-field escape angle.
    room_forward: float
    room_reverse: float
    # Guess factors of recent enemy hits on us, relative to our sideways motion when each shot was fired.
    recent_hit_guess_factors: tuple[float, ...]


def hit_region(guess_factor: float) -> str:
    if guess_factor > 0.5:
        return "far ahead"
    if guess_factor > 0.15:
        return "slightly ahead"
    if guess_factor >= -0.15:
        return "where we were"
    if guess_factor >= -0.5:
        return "slightly behind"
    return "far behind"


def _share_name(share: float) -> str:
    return bucket(share, ((1e-9, "none"), (0.2, "few"), (0.5, "some")), "most")


def surf_state(features: SurfFeatures) -> dict[str, Any]:
    if features.own_speed < 1.0:
        moving = "almost stopped"
    elif features.own_lateral_share >= 0.6:
        moving = "sideways to the enemy"
    else:
        moving = "toward or away from the enemy"
    room = ((0.4, "a wall is close"), (0.8, "limited"))
    hits = features.recent_hit_guess_factors
    if hits:
        counts = {region: 0 for region in HIT_REGIONS}
        for guess_factor in hits:
            counts[hit_region(guess_factor)] += 1
        recent_hits: dict[str, str] | str = {region: _share_name(count / len(hits)) for region, count in counts.items()}
    else:
        recent_hits = "no hits yet"
    return {
        "incoming_bullet": {
            "distance": bucket(features.distance, ((150.0, "very close"), (300.0, "close"), (500.0, "medium")), "far"),
            "power": bucket(features.bullet_power, ((1.2, "low"), (2.2, "medium")), "high"),
            "arrives_in": bucket(features.flight_turns, ((15.0, "under 15 turns"), (30.0, "15 to 30 turns")), "over 30 turns"),
        },
        "us": {
            "moving": moving,
            "room_ahead": bucket(features.room_forward, room, "plenty"),
            "room_behind": bucket(features.room_reverse, room, "plenty"),
        },
        "recent_hits_on_us": recent_hits,
        "hits_counted": bucket(len(hits), ((1, "none"), (5, "a few"), (15, "several")), "many"),
    }
