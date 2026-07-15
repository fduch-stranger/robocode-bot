from bot_core.combat import CombatProfileSnapshot, CombatTotals, OwnBulletResolution
from bot_core.telemetry.sink import TelemetrySink


class CombatTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def sample_profile(self, snapshot: CombatProfileSnapshot) -> None:
        self._sink.sample("combat.profile", **_profile_fields(snapshot))

    def record_profile(self, snapshot: CombatProfileSnapshot) -> None:
        self._sink.log("combat.profile", **_profile_fields(snapshot))

    def record_own_bullet_resolution(self, resolution: OwnBulletResolution) -> None:
        event = "bullet.resolution_corrected" if resolution.previous_outcome is not None else "bullet.resolved"
        self._sink.log(event, **_resolution_fields(resolution))


def _profile_fields(snapshot: CombatProfileSnapshot) -> dict[str, object]:
    return {
        "version": 1,
        "target": snapshot.target_id,
        "recent_window_start": snapshot.recent_window_start,
        "recent_window_end": snapshot.turn,
        "tags": list(snapshot.tags),
        **_totals_fields("recent", snapshot.recent),
        **_totals_fields("lifetime", snapshot.lifetime),
    }


def _totals_fields(prefix: str, totals: CombatTotals) -> dict[str, object]:
    return {
        f"{prefix}_own_accepted_shots": totals.own_accepted_shots,
        f"{prefix}_own_resolved_shots": totals.own_resolved_shots,
        f"{prefix}_own_hits": totals.own_hits,
        f"{prefix}_own_misses": totals.own_misses,
        f"{prefix}_own_fired_energy": round(totals.own_fired_energy, 3),
        f"{prefix}_own_hit_damage": round(totals.own_hit_damage, 3),
        f"{prefix}_own_hit_rate": round(totals.own_hit_rate, 4),
        f"{prefix}_own_damage_per_accepted_shot": round(totals.own_damage_per_accepted_shot, 4),
        f"{prefix}_own_damage_per_fired_energy": round(totals.own_damage_per_fired_energy, 4),
        f"{prefix}_own_resolution_coverage": round(totals.own_resolution_coverage, 4),
        f"{prefix}_enemy_inferred_shots": totals.enemy_inferred_shots,
        f"{prefix}_enemy_weighted_shots": round(totals.enemy_weighted_shots, 3),
        f"{prefix}_enemy_average_fire_confidence": round(totals.enemy_average_fire_confidence, 4),
        f"{prefix}_enemy_inferred_fired_energy": round(totals.enemy_inferred_fired_energy, 3),
        f"{prefix}_enemy_weighted_fired_energy": round(totals.enemy_weighted_fired_energy, 3),
        f"{prefix}_enemy_hits": totals.enemy_hits,
        f"{prefix}_enemy_hit_damage": round(totals.enemy_hit_damage, 3),
        f"{prefix}_enemy_hits_matched": totals.enemy_hits_matched,
        f"{prefix}_enemy_hit_match_coverage": round(totals.enemy_hit_match_coverage, 4),
        f"{prefix}_damage_delta": round(totals.damage_delta, 3),
    }


def _resolution_fields(resolution: OwnBulletResolution) -> dict[str, object]:
    fields: dict[str, object] = {
        "bullet_id": resolution.bullet_id,
        "target": resolution.target_id,
        "fired_turn": resolution.fired_turn,
        "resolved_turn": resolution.resolved_turn,
        "power": round(resolution.power, 3),
        "outcome": resolution.outcome,
        "damage": round(resolution.damage, 3),
    }
    if resolution.gun_mode is not None:
        fields["aim_mode"] = resolution.gun_mode
    if resolution.source is not None:
        fields["source"] = resolution.source
    if resolution.previous_outcome is not None:
        fields["previous_outcome"] = resolution.previous_outcome
    return fields
