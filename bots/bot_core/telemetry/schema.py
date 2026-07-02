from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


CANONICAL_FIELDS = frozenset(
    {
        "target",
        "distance",
        "power",
        "damage",
        "bullet_id",
        "aim_mode",
        "gun_mode",
        "movement_mode",
        "mode",
        "evasion",
        "evading",
        "wall_risk",
        "reason",
    }
)


@dataclass(frozen=True)
class TelemetryEventSpec:
    category: str
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    aliases: Mapping[str, tuple[str, ...]] | None = None

    def normalized_fields(self, fields: Mapping[str, object]) -> dict[str, object]:
        normalized = dict(fields)
        for canonical, aliases in (self.aliases or {}).items():
            if normalized.get(canonical) not in (None, ""):
                continue
            for alias in aliases:
                if fields.get(alias) not in (None, ""):
                    normalized[canonical] = fields[alias]
                    break
        return normalized


EVENT_SPECS: dict[str, TelemetryEventSpec] = {
    "telemetry.session": TelemetryEventSpec("lifecycle"),
    "telemetry.dropped": TelemetryEventSpec("lifecycle", required_fields=("count",)),
    "round.reset": TelemetryEventSpec("lifecycle", optional_fields=("previous_turn", "current_turn")),
    "scan.new": TelemetryEventSpec(
        "targeting",
        optional_fields=("bot_id", "energy", "x", "y"),
        aliases={"target": ("bot_id",)},
    ),
    "scan.reacquired": TelemetryEventSpec(
        "targeting",
        optional_fields=("bot_id", "previous_age", "previous_x", "previous_y", "x", "y"),
        aliases={"target": ("bot_id",)},
    ),
    "target.select": TelemetryEventSpec(
        "targeting",
        required_fields=("selected",),
        optional_fields=("previous", "score", "fresh_candidates", "candidate", "candidate_score", "previous_age", "known_targets"),
        aliases={"target": ("selected",)},
    ),
    "target.drop_lost": TelemetryEventSpec(
        "targeting",
        optional_fields=("bot_id", "age", "cached_x", "cached_y", "cached_distance", "known_targets"),
        aliases={"target": ("bot_id",)},
    ),
    "target.stale": TelemetryEventSpec("targeting", optional_fields=("bot_id",), aliases={"target": ("bot_id",)}),
    "target.dead": TelemetryEventSpec("targeting", optional_fields=("bot_id",), aliases={"target": ("bot_id",)}),
    "target.reacquire": TelemetryEventSpec("targeting", optional_fields=("target", "age", "distance", "radar_mode")),
    "search": TelemetryEventSpec("targeting", optional_fields=("known_targets",)),
    "search.wall_avoid": TelemetryEventSpec("movement", optional_fields=("x", "y", "center_bearing", "evade_direction", "near_wall")),
    "track": TelemetryEventSpec(
        "fire",
        required_fields=("target", "distance", "gun_bearing", "aim_mode"),
        optional_fields=(
            "age",
            "radar_bearing",
            "radar_turn",
            "radar_mode",
            "radar_target",
            "radar_age",
            "predicted_x",
            "predicted_y",
            "aim_guess_factor",
            "gun_samples",
            "gun_scores",
            "firepower",
            "hold_reason",
            "fire_alignment_limit",
            "movement_mode",
            "known_targets",
        ),
        aliases={"power": ("firepower",), "reason": ("hold_reason",)},
    ),
    "gun.switch": TelemetryEventSpec(
        "fire",
        required_fields=("selected",),
        optional_fields=("target", "previous", "scores"),
        aliases={"aim_mode": ("selected",), "gun_mode": ("selected",)},
    ),
    "gun.switch_decision": TelemetryEventSpec(
        "fire",
        required_fields=("selected",),
        optional_fields=("target", "previous", "changed", "candidates"),
        aliases={"aim_mode": ("selected",), "gun_mode": ("selected",)},
    ),
    "gun.wave_visit": TelemetryEventSpec(
        "fire",
        optional_fields=("target", "guess_factor", "samples", "traveled", "distance", "selected_gun", "virtual_scores", "gun_scores"),
        aliases={"aim_mode": ("selected_gun",), "gun_mode": ("selected_gun",)},
    ),
    "gun.eval_wave_visit": TelemetryEventSpec(
        "fire",
        optional_fields=("target", "guess_factor", "samples", "traveled", "distance", "selected_gun", "virtual_scores", "gun_scores"),
        aliases={"aim_mode": ("selected_gun",), "gun_mode": ("selected_gun",)},
    ),
    "bullet.fired": TelemetryEventSpec(
        "fire",
        required_fields=("bullet_id", "power", "aim_mode"),
        optional_fields=("target", "direction", "energy", "gun_waves", "gun_samples", "gun_confidence", "gun_confidence_visits"),
    ),
    "bullet.hit_bot": TelemetryEventSpec(
        "fire",
        required_fields=("bullet_id", "power", "damage", "energy"),
        optional_fields=("victim", "target", "aim_mode"),
        aliases={"target": ("victim",)},
    ),
    "enemy.fire_detected": TelemetryEventSpec(
        "energy",
        required_fields=("power", "distance", "evasion"),
        optional_fields=(
            "bot_id",
            "raw_drop",
            "corrected_drop",
            "correction",
            "scan_gap",
            "bullet_travel_ticks",
            "evading",
            "evade_direction",
            "move_direction",
            "evade_until",
            "movement_wave",
            "predicted_power",
            "prediction_confidence",
            "prediction_reason",
            "prediction_error",
            "power_samples",
            "power_mae",
        ),
        aliases={"target": ("bot_id",)},
    ),
    "enemy.energy_drop_ignored": TelemetryEventSpec(
        "energy",
        required_fields=("reason",),
        optional_fields=("bot_id", "raw_drop", "corrected_drop", "correction", "scan_gap", "distance"),
        aliases={"target": ("bot_id",)},
    ),
    "enemy.gun_heat_wave": TelemetryEventSpec(
        "energy",
        required_fields=("power", "distance", "reason"),
        optional_fields=("bot_id", "confidence", "samples", "power_mae", "target_age", "movement_wave"),
        aliases={"target": ("bot_id",)},
    ),
    "movement.profile_visit": TelemetryEventSpec(
        "movement",
        optional_fields=("target", "guess_factor", "bin", "bucket", "visits", "wave_age", "ensemble_danger", "ensemble_samples"),
    ),
    "movement.flatten": TelemetryEventSpec(
        "movement",
        optional_fields=("target", "current_direction", "suggested_direction", "bucket", "current_count", "alternative_count", "distance", "reason"),
    ),
    "movement.flatten_shadow": TelemetryEventSpec(
        "movement",
        optional_fields=("target", "current_direction", "suggested_direction", "bucket", "current_count", "alternative_count", "distance", "reason"),
    ),
    "movement.duel_flatten": TelemetryEventSpec("movement", optional_fields=("target", "suggested_direction", "distance")),
    "movement.goto_surf": TelemetryEventSpec(
        "movement",
        optional_fields=("target", "destination_x", "destination_y", "danger", "wave_kind", "turn", "speed"),
        aliases={"movement_mode": ("mode",)},
    ),
    "movement.duel_potential": TelemetryEventSpec(
        "movement",
        optional_fields=("target", "destination_x", "destination_y", "force_x", "force_y", "distance", "mode", "evading", "turn", "speed"),
        aliases={"movement_mode": ("mode",)},
    ),
    "movement.minimum_risk": TelemetryEventSpec(
        "movement",
        optional_fields=(
            "target",
            "destination_x",
            "destination_y",
            "risk",
            "candidates",
            "nearest_enemy",
            "nearest_enemy_distance",
            "reused_destination",
            "destination_age",
            "turn",
            "speed",
            "known_targets",
            "fire_threat",
        ),
        aliases={"movement_mode": ("mode",)},
    ),
    "wall.avoid": TelemetryEventSpec("movement", optional_fields=("x", "y", "center_bearing", "move_direction", "evade_direction", "target")),
    "separate": TelemetryEventSpec("movement", optional_fields=("target", "distance", "away_bearing", "target_speed", "turn_limit", "move_direction")),
    "hit.bullet": TelemetryEventSpec(
        "combat",
        required_fields=("owner", "power", "damage", "energy"),
        optional_fields=("bullet_direction", "wall_risk", "near_wall", "evade_direction", "move_direction"),
    ),
    "hit.wall": TelemetryEventSpec("combat", optional_fields=("evade_direction", "move_direction", "center_bearing", "wall_escape_until")),
    "hit.bot": TelemetryEventSpec("combat", optional_fields=("target", "energy", "rammed", "distance", "near_wall", "wall_risk")),
}


EXPECTED_EVASION_LABELS = frozenset({"active_duel", "active_melee", "threat_only"})


def event_spec(event_name: str) -> TelemetryEventSpec | None:
    return EVENT_SPECS.get(event_name)


def normalize_fields(event_name: str, fields: Mapping[str, object]) -> dict[str, object]:
    spec = event_spec(event_name)
    if spec is None:
        return dict(fields)
    return spec.normalized_fields(fields)


def missing_required_fields(event_name: str, fields: Mapping[str, object]) -> tuple[str, ...]:
    spec = event_spec(event_name)
    if spec is None:
        return ()
    normalized = spec.normalized_fields(fields)
    return tuple(field for field in spec.required_fields if normalized.get(field) in (None, ""))
