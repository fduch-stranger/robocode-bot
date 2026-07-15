#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys
from collections.abc import Iterator
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bots"))

from bot_core.combat import (
    FireUtilityConfig,
    cooldown_turns_for_power,
    power_band_for,
    quality_band_for,
    range_band_for,
)
from bot_core.physics import (
    bullet_damage_for_power,
    bullet_hit_bonus_for_power,
    gun_heat_for_power,
)
from bot_core.telemetry.schema import EXPECTED_EVASION_LABELS, event_spec, missing_required_fields, normalize_fields

EXPECTED_MOVEMENT_FALLBACK_LEVELS = {"occupancy", "blended", "hit_profile"}
EXPECTED_FIRE_UTILITY_FALLBACK_LEVELS = {
    "dynamic_quality",
    "dynamic_quality_prior",
    "global",
    "global_prior",
}
FIRE_UTILITY_EVENTS = {
    "fire.utility_opportunity",
    "fire.utility_accepted",
    "fire.utility_outcome",
    "fire.utility_outcome_corrected",
}
FIRE_UTILITY_CONFIG = FireUtilityConfig()


def main() -> int:
    args = _parse_args()
    telemetry_dir = Path(args.telemetry_dir)
    events = list(_read_events(telemetry_dir))
    issues = _audit(events, args.require_bots)
    summary = _summary(events, issues)
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print_summary(summary)
    return 1 if issues else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Robocode bot telemetry JSONL files.")
    parser.add_argument("telemetry_dir", help="Directory containing telemetry JSONL files.")
    parser.add_argument(
        "--require-bot",
        action="append",
        default=[],
        dest="require_bots",
        help="Bot name that must have at least one telemetry event. Can be repeated.",
    )
    parser.add_argument("--json-output", help="Write structured audit JSON to this path.")
    return parser.parse_args()


def _read_events(telemetry_dir: Path) -> Iterator[dict[str, Any]]:
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    yield {
                        "bot": path.stem,
                        "event": "telemetry.decode_error",
                        "fields": {"error": str(error)},
                        "file": path.name,
                        "line": line_number,
                    }
                    continue
                event["file"] = path.name
                event["line"] = line_number
                yield event


def _audit(events: list[dict[str, Any]], required_bots: list[str]) -> list[str]:
    issues: list[str] = []
    bots = {str(event.get("bot")) for event in events if event.get("bot")}
    shots_by_bot: dict[str, dict[str, str]] = defaultdict(dict)
    pending_hits_by_bot: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    pending_unattributed_by_bot: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    resolved_by_bot: dict[str, set[str]] = defaultdict(set)
    resolved_outcome_by_bot: dict[str, dict[str, str]] = defaultdict(dict)
    shot_power_by_bot: dict[str, dict[str, float]] = defaultdict(dict)
    utility_accepted_by_bot: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    utility_resolved_by_bot: dict[str, set[str]] = defaultdict(set)
    utility_outcome_by_bot: dict[str, dict[str, str]] = defaultdict(dict)
    utility_observed_resolved_by_bot: dict[str, int] = defaultdict(int)
    utility_observed_hits_by_bot: dict[str, int] = defaultdict(int)
    profile_totals_by_bot: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    round_profile_base_by_bot: dict[str, int] = defaultdict(int)
    terminal_round_by_bot: dict[str, bool] = defaultdict(bool)
    resolution_enabled_bots = {
        str(event.get("bot") or "?")
        for event in events
        if event.get("event") in {"bullet.resolved", "bullet.resolution_corrected"}
    }
    utility_enabled_bots = {
        str(event.get("bot") or "?")
        for event in events
        if event.get("event") in FIRE_UTILITY_EVENTS
        or (
            event.get("event") == "bot.config"
            and isinstance(event.get("fields"), dict)
            and bool(event["fields"].get("fire_utility_shadow"))
        )
    }

    for bot_name in required_bots:
        if bot_name not in bots:
            issues.append(f"missing bot telemetry: {bot_name}")

    for event in events:
        name = str(event.get("event") or "")
        raw_fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        fields = normalize_fields(name, raw_fields)
        bot = str(event.get("bot") or "?")
        location = f"{event.get('file')}:{event.get('line')}"
        if _is_terminal_event(event, name, fields):
            terminal_round_by_bot[bot] = True

        if name == "telemetry.decode_error":
            issues.append(f"{location} invalid json: {fields.get('error')}")
            continue

        for field in missing_required_fields(name, raw_fields):
            issues.append(f"{location} {bot} {name} missing {field}")

        if name and event_spec(name) is None:
            continue

        if name == "round.reset":
            _flush_unattributed_hits(issues, bot, pending_unattributed_by_bot[bot])
            _flush_unresolved_shots(
                issues,
                bot,
                shots_by_bot[bot],
                resolved_by_bot[bot],
                resolution_enabled_bots,
                profile_totals_by_bot[bot],
                round_profile_base_by_bot[bot],
                terminal_round_by_bot[bot],
            )
            _flush_fire_utility_round(
                issues,
                bot,
                shots_by_bot[bot],
                utility_accepted_by_bot[bot],
                utility_resolved_by_bot[bot],
                utility_enabled_bots,
                terminal_round_by_bot[bot],
            )
            round_profile_base_by_bot[bot] = sum(accepted for accepted, _ in profile_totals_by_bot[bot].values())
            shots_by_bot[bot].clear()
            resolved_by_bot[bot].clear()
            resolved_outcome_by_bot[bot].clear()
            shot_power_by_bot[bot].clear()
            utility_accepted_by_bot[bot].clear()
            utility_resolved_by_bot[bot].clear()
            utility_outcome_by_bot[bot].clear()
            pending_hits_by_bot[bot].clear()
            pending_unattributed_by_bot[bot].clear()
            terminal_round_by_bot[bot] = False
            continue

        if name in FIRE_UTILITY_EVENTS:
            _audit_fire_utility_fields(
                issues,
                location,
                bot,
                name,
                fields,
                max_resolved_support=utility_observed_resolved_by_bot[bot],
                max_hit_support=utility_observed_hits_by_bot[bot],
            )

        if name == "fire.utility_opportunity":
            action = fields.get("action")
            reason = fields.get("reason")
            if action not in {"fire", "hold"}:
                issues.append(
                    f"{location} {bot} fire.utility_opportunity has unexpected action={action!r}"
                )
            if action == "fire" and reason not in {"ready", "last_stand"}:
                issues.append(
                    f"{location} {bot} fire.utility_opportunity fires with hold reason={reason!r}"
                )
            if action == "hold" and reason in {"ready", "last_stand"}:
                issues.append(
                    f"{location} {bot} fire.utility_opportunity holds with fire reason={reason!r}"
                )
            continue

        if name == "fire.utility_accepted" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            fired_mode = shots_by_bot[bot].get(bullet_id)
            accepted_mode = fields.get("aim_mode")
            fired_power = shot_power_by_bot[bot].get(bullet_id)
            accepted_power = _numeric(fields.get("power"))
            if bullet_id in utility_accepted_by_bot[bot]:
                issues.append(
                    f"{location} {bot} fire.utility_accepted duplicates bullet_id={bullet_id}"
                )
            elif fired_mode is None:
                issues.append(
                    f"{location} {bot} fire.utility_accepted has no accepted bullet.fired for bullet_id={bullet_id}"
                )
            elif accepted_mode not in (None, "") and str(accepted_mode) != fired_mode:
                issues.append(
                    f"{location} {bot} fire.utility_accepted aim_mode={accepted_mode} "
                    f"does not match fired aim_mode={fired_mode}"
                )
            if (
                fired_power is not None
                and accepted_power is not None
                and abs(fired_power - accepted_power) > 1e-4
            ):
                issues.append(
                    f"{location} {bot} fire.utility_accepted power={accepted_power} "
                    f"does not match fired power={fired_power}"
                )
            if fields.get("action") != "fire":
                issues.append(
                    f"{location} {bot} fire.utility_accepted action is not fire"
                )
            if fields.get("reason") == "accepted_unstaged":
                issues.append(
                    f"{location} {bot} fire.utility_accepted has no staged ready-gun opportunity"
                )
            utility_accepted_by_bot[bot][bullet_id] = dict(fields)
            continue

        if name in {"fire.utility_outcome", "fire.utility_outcome_corrected"} and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            accepted = utility_accepted_by_bot[bot].get(bullet_id)
            corrected = name == "fire.utility_outcome_corrected"
            if accepted is None:
                issues.append(
                    f"{location} {bot} {name} has no fire.utility_accepted for bullet_id={bullet_id}"
                )
            elif corrected and bullet_id not in utility_resolved_by_bot[bot]:
                issues.append(
                    f"{location} {bot} fire.utility_outcome_corrected has no prior utility outcome"
                )
            elif not corrected and bullet_id in utility_resolved_by_bot[bot]:
                issues.append(
                    f"{location} {bot} fire.utility_outcome duplicates bullet_id={bullet_id}"
                )
            if accepted is not None:
                for field in ("q", "power"):
                    accepted_value = _numeric(accepted.get(field))
                    outcome_value = _numeric(fields.get(field))
                    if (
                        accepted_value is not None
                        and outcome_value is not None
                        and abs(accepted_value - outcome_value) > 1e-6
                    ):
                        issues.append(
                            f"{location} {bot} {name} {field}={outcome_value} "
                            f"does not match accepted {field}={accepted_value}"
                        )
                accepted_mode = accepted.get("aim_mode")
                if fields.get("aim_mode") not in (None, "", accepted_mode):
                    issues.append(
                        f"{location} {bot} {name} aim_mode={fields.get('aim_mode')} "
                        f"does not match accepted aim_mode={accepted_mode}"
                    )
            expected_hit = fields.get("outcome") == "hit_bot"
            if fields.get("hit") is not expected_hit:
                issues.append(
                    f"{location} {bot} {name} hit={fields.get('hit')!r} "
                    f"does not match outcome={fields.get('outcome')!r}"
                )
            if corrected and fields.get("previous_outcome") in (None, ""):
                issues.append(
                    f"{location} {bot} fire.utility_outcome_corrected is missing previous_outcome"
                )
            elif corrected and (
                fields.get("previous_outcome") != "round_end" or not expected_hit
            ):
                issues.append(
                    f"{location} {bot} fire.utility_outcome_corrected is not a round_end-to-hit_bot correction"
                )
            prior_outcome = utility_outcome_by_bot[bot].get(bullet_id)
            if (
                corrected
                and prior_outcome is not None
                and fields.get("previous_outcome") != prior_outcome
            ):
                issues.append(
                    f"{location} {bot} fire.utility_outcome_corrected previous_outcome="
                    f"{fields.get('previous_outcome')} does not match prior outcome={prior_outcome}"
                )
            if accepted is not None and not corrected and prior_outcome is None:
                utility_observed_resolved_by_bot[bot] += 1
                if expected_hit:
                    utility_observed_hits_by_bot[bot] += 1
                utility_outcome_by_bot[bot][bullet_id] = str(
                    fields.get("outcome") or "unknown"
                )
            elif (
                accepted is not None
                and corrected
                and prior_outcome == "round_end"
                and fields.get("previous_outcome") == "round_end"
                and expected_hit
            ):
                utility_observed_hits_by_bot[bot] += 1
                utility_outcome_by_bot[bot][bullet_id] = "hit_bot"
            utility_resolved_by_bot[bot].add(bullet_id)
            continue

        if name == "bullet.resolved" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            fired_mode = shots_by_bot[bot].get(bullet_id)
            resolved_mode = fields.get("aim_mode")
            if bullet_id in resolved_by_bot[bot]:
                issues.append(f"{location} {bot} bullet.resolved duplicates bullet_id={bullet_id}")
            elif fired_mode is None:
                issues.append(f"{location} {bot} bullet.resolved has no accepted bullet.fired for bullet_id={bullet_id}")
            elif resolved_mode not in (None, "") and str(resolved_mode) != fired_mode:
                issues.append(
                    f"{location} {bot} bullet.resolved aim_mode={resolved_mode} "
                    f"does not match fired aim_mode={fired_mode}"
                )
            resolved_by_bot[bot].add(bullet_id)
            resolved_outcome_by_bot[bot][bullet_id] = str(
                fields.get("outcome") or "unknown"
            )
            continue

        if name == "bullet.resolution_corrected" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            fired_mode = shots_by_bot[bot].get(bullet_id)
            corrected_mode = fields.get("aim_mode")
            if bullet_id not in resolved_by_bot[bot]:
                issues.append(f"{location} {bot} bullet.resolution_corrected has no prior bullet.resolved outcome")
            elif (
                fields.get("previous_outcome") != "round_end"
                or fields.get("outcome") != "hit_bot"
            ):
                issues.append(
                    f"{location} {bot} bullet.resolution_corrected is not a round_end-to-hit_bot correction"
                )
            elif resolved_outcome_by_bot[bot].get(bullet_id) != "round_end":
                issues.append(
                    f"{location} {bot} bullet.resolution_corrected prior outcome="
                    f"{resolved_outcome_by_bot[bot].get(bullet_id)} is not round_end"
                )
            elif fired_mode is None:
                issues.append(
                    f"{location} {bot} bullet.resolution_corrected has no accepted bullet.fired for bullet_id={bullet_id}"
                )
            elif corrected_mode not in (None, "") and str(corrected_mode) != fired_mode:
                issues.append(
                    f"{location} {bot} bullet.resolution_corrected aim_mode={corrected_mode} "
                    f"does not match fired aim_mode={fired_mode}"
                )
            else:
                resolved_outcome_by_bot[bot][bullet_id] = "hit_bot"
            continue

        if name == "bullet.fired" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            aim_mode = fields.get("aim_mode")
            if aim_mode not in (None, ""):
                fired_mode = str(aim_mode)
                shots_by_bot[bot][bullet_id] = fired_mode
                power = _numeric(fields.get("power"))
                if power is not None:
                    shot_power_by_bot[bot][bullet_id] = power
                pending_unattributed_by_bot[bot].pop(bullet_id, None)
                for hit_location, hit_mode in pending_hits_by_bot[bot].pop(bullet_id, []):
                    if hit_mode != fired_mode:
                        issues.append(
                            f"{hit_location} {bot} bullet.hit_bot aim_mode={hit_mode} "
                            f"does not match fired aim_mode={fired_mode}"
                        )
            continue

        if name == "bullet.hit_bot" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            hit_mode = fields.get("aim_mode")
            fired_mode = shots_by_bot[bot].get(bullet_id)
            if hit_mode in (None, "") and fired_mode in (None, ""):
                pending_unattributed_by_bot[bot][bullet_id].append(location)
            elif hit_mode not in (None, "") and fired_mode not in (None, "") and str(hit_mode) != fired_mode:
                issues.append(
                    f"{location} {bot} bullet.hit_bot aim_mode={hit_mode} does not match fired aim_mode={fired_mode}"
                )
            elif hit_mode not in (None, "") and fired_mode in (None, ""):
                pending_hits_by_bot[bot][bullet_id].append((location, str(hit_mode)))

        if name == "enemy.fire_detected":
            evasion = fields.get("evasion")
            if evasion not in EXPECTED_EVASION_LABELS:
                issues.append(f"{location} {bot} enemy.fire_detected has unexpected evasion={evasion!r}")

        if name == "movement.profile_visit":
            evidence_kind = fields.get("evidence_kind")
            occupancy_visits = _numeric(fields.get("occupancy_visits"))
            if evidence_kind == "expected_expired" and occupancy_visits not in (None, 0.0):
                issues.append(f"{location} {bot} expired expected wave persisted occupancy evidence")
            if evidence_kind == "occupancy" and fields.get("wave_kind") not in (None, "confirmed"):
                issues.append(f"{location} {bot} occupancy evidence came from a non-confirmed wave")

        if name == "movement.evidence_shadow":
            fallback = fields.get("hit_fallback_level")
            if fallback not in EXPECTED_MOVEMENT_FALLBACK_LEVELS:
                issues.append(f"{location} {bot} movement.evidence_shadow has unexpected fallback={fallback!r}")
            for field in (
                "current_occupancy",
                "alternative_occupancy",
                "current_hit_danger",
                "alternative_hit_danger",
                "current_expected_pressure",
                "alternative_expected_pressure",
                "current_shadow_danger",
                "alternative_shadow_danger",
                "hit_profile_support",
            ):
                value = _numeric(fields.get(field))
                if value is not None and value < 0.0:
                    issues.append(f"{location} {bot} movement.evidence_shadow has negative {field}")

        if name == "combat.profile":
            _audit_combat_profile(issues, location, bot, fields)
            target = fields.get("target")
            accepted = _whole_number(fields.get("lifetime_own_accepted_shots"))
            resolved = _whole_number(fields.get("lifetime_own_resolved_shots"))
            if accepted is not None and resolved is not None:
                target_key = str(target) if target is not None else "unattributed"
                profile_totals_by_bot[bot][target_key] = (accepted, resolved)

    for bot, pending_hits in pending_unattributed_by_bot.items():
        _flush_unattributed_hits(issues, bot, pending_hits)
    for bot, shots in shots_by_bot.items():
        _flush_unresolved_shots(
            issues,
            bot,
            shots,
            resolved_by_bot[bot],
            resolution_enabled_bots,
            profile_totals_by_bot[bot],
            round_profile_base_by_bot[bot],
            terminal_round_by_bot[bot],
        )
    for bot in utility_enabled_bots | set(utility_accepted_by_bot):
        _flush_fire_utility_round(
            issues,
            bot,
            shots_by_bot[bot],
            utility_accepted_by_bot[bot],
            utility_resolved_by_bot[bot],
            utility_enabled_bots,
            terminal_round_by_bot[bot],
        )

    return issues



def _audit_fire_utility_fields(
    issues: list[str],
    location: str,
    bot: str,
    name: str,
    fields: dict[str, object],
    *,
    max_resolved_support: int,
    max_hit_support: int,
) -> None:
    q = _numeric(fields.get("q"))
    support = _whole_number(fields.get("calibration_support"))
    hits = _whole_number(fields.get("calibration_hits"))
    fallback = fields.get("fallback_level")
    solution_quality = _numeric(fields.get("solution_quality"))
    aim_mode = str(fields.get("aim_mode") or "unknown")
    dynamic_high_quality = (
        aim_mode == "dynamic_cluster"
        and solution_quality is not None
        and solution_quality >= FIRE_UTILITY_CONFIG.dynamic_high_quality
    )
    if q is not None and not 0.0 <= q <= 1.0:
        issues.append(f"{location} {bot} {name} q is outside [0, 1]")
    if support is not None and support < 0:
        issues.append(f"{location} {bot} {name} has negative calibration_support")
    if hits is not None and (hits < 0 or (support is not None and hits > support)):
        issues.append(f"{location} {bot} {name} has invalid calibration_hits")
    if support is not None and support > max_resolved_support:
        issues.append(
            f"{location} {bot} {name} calibration_support={support} exceeds "
            f"prior resolved outcomes={max_resolved_support}"
        )
    if hits is not None and hits > max_hit_support:
        issues.append(
            f"{location} {bot} {name} calibration_hits={hits} exceeds "
            f"prior hit outcomes={max_hit_support}"
        )
    if q is not None and support is not None and hits is not None:
        prior_total = FIRE_UTILITY_CONFIG.prior_hits + FIRE_UTILITY_CONFIG.prior_misses
        expected_q = (hits + FIRE_UTILITY_CONFIG.prior_hits) / (support + prior_total)
        if dynamic_high_quality:
            adjusted_numerator = (
                expected_q * FIRE_UTILITY_CONFIG.dynamic_high_quality_odds_multiplier
            )
            adjusted_denominator = 1.0 - expected_q + adjusted_numerator
            expected_q = (
                adjusted_numerator / adjusted_denominator
                if adjusted_denominator > 0.0
                else 0.0
            )
        if abs(q - expected_q) > 2e-6:
            issues.append(
                f"{location} {bot} {name} q={q} does not match "
                f"posterior={expected_q:.6f}"
            )
    if fallback not in EXPECTED_FIRE_UTILITY_FALLBACK_LEVELS:
        issues.append(f"{location} {bot} {name} has unexpected fallback={fallback!r}")
    elif support is not None:
        expected_fallback = (
            "dynamic_quality" if support else "dynamic_quality_prior"
        ) if dynamic_high_quality else ("global" if support else "global_prior")
        if fallback != expected_fallback:
            issues.append(
                f"{location} {bot} {name} fallback={fallback} does not match "
                f"context/support={expected_fallback}"
            )
        if fallback in {"global_prior", "dynamic_quality_prior"} and support != 0:
            issues.append(
                f"{location} {bot} {name} {fallback} has nonzero support={support}"
            )

    power = _numeric(fields.get("power"))
    distance = _numeric(fields.get("distance"))
    model_support = _whole_number(fields.get("model_support"))
    if power is not None:
        if not 0.1 <= power <= 3.0:
            issues.append(f"{location} {bot} {name} power is outside [0.1, 3.0]")
        expected_power_band = power_band_for(power)
        power_near_boundary = any(
            abs(power - boundary) <= 1e-6
            for boundary in (
                FIRE_UTILITY_CONFIG.low_power,
                FIRE_UTILITY_CONFIG.high_power,
            )
        )
        if (
            fields.get("power_band") not in (None, expected_power_band)
            and not power_near_boundary
        ):
            issues.append(
                f"{location} {bot} {name} power_band={fields.get('power_band')!r} "
                f"does not match power={power}"
            )
        expected_values = {
            "bullet_damage": bullet_damage_for_power(power),
            "hit_bonus": bullet_hit_bonus_for_power(power),
            "gun_heat": gun_heat_for_power(power),
        }
        for field, expected in expected_values.items():
            actual = _numeric(fields.get(field))
            if actual is not None and abs(actual - expected) > 1e-4:
                issues.append(
                    f"{location} {bot} {name} {field}={actual} does not match {expected:.4f}"
                )
    if distance is not None:
        expected_range_band = range_band_for(distance)
        distance_near_boundary = any(
            abs(distance - boundary) <= 1e-6
            for boundary in (
                FIRE_UTILITY_CONFIG.near_distance,
                FIRE_UTILITY_CONFIG.far_distance,
            )
        )
        if (
            fields.get("range_band") not in (None, expected_range_band)
            and not distance_near_boundary
        ):
            issues.append(
                f"{location} {bot} {name} range_band={fields.get('range_band')!r} "
                f"does not match distance={distance}"
            )
    if model_support is not None:
        expected_quality_band = quality_band_for(
            aim_mode,
            solution_quality,
            model_support,
        )
        quality_near_boundary = (
            aim_mode == "dynamic_cluster"
            and solution_quality is not None
            and any(
                abs(solution_quality - boundary) <= 1e-6
                for boundary in (FIRE_UTILITY_CONFIG.dynamic_high_quality,)
            )
        )
        if (
            fields.get("quality_band") not in (None, expected_quality_band)
            and not quality_near_boundary
        ):
            issues.append(
                f"{location} {bot} {name} quality_band={fields.get('quality_band')!r} "
                f"does not match mode quality/support"
            )

    damage = _numeric(fields.get("bullet_damage"))
    bonus = _numeric(fields.get("hit_bonus"))
    score_utility = _numeric(fields.get("score_utility"))
    energy_utility = _numeric(fields.get("energy_swing_utility"))
    if q is not None and power is not None and damage is not None:
        expected_score = q * damage
        if score_utility is not None and abs(score_utility - expected_score) > 1e-4:
            issues.append(
                f"{location} {bot} {name} score_utility={score_utility} "
                f"does not match q*D={expected_score:.6f}"
            )
        if bonus is not None:
            expected_energy = q * (damage + bonus) - power
            if energy_utility is not None and abs(energy_utility - expected_energy) > 1e-4:
                issues.append(
                    f"{location} {bot} {name} energy_swing_utility={energy_utility} "
                    f"does not match q*(D+B)-p={expected_energy:.6f}"
                )

    cooling_rate = _numeric(fields.get("cooling_rate"))
    cooldown_turns = _whole_number(fields.get("cooldown_turns"))
    if cooling_rate is not None and power is not None and cooldown_turns is not None:
        expected_turns = cooldown_turns_for_power(power, cooling_rate)
        if cooldown_turns != expected_turns:
            issues.append(
                f"{location} {bot} {name} cooldown_turns={cooldown_turns} "
                f"does not match power/cooling_rate={expected_turns}"
            )


def _flush_fire_utility_round(
    issues: list[str],
    bot: str,
    fired: dict[str, str],
    accepted: dict[str, dict[str, object]],
    resolved: set[str],
    enabled_bots: set[str],
    terminal_round: bool,
) -> None:
    if bot not in enabled_bots and not accepted:
        return
    for bullet_id in sorted(set(fired) - set(accepted)):
        issues.append(
            f"{bot} bullet.fired has no fire.utility_accepted for bullet_id={bullet_id}"
        )
    if not terminal_round:
        for bullet_id in sorted(set(accepted) - resolved):
            issues.append(
                f"{bot} fire.utility_accepted has no utility outcome for bullet_id={bullet_id}"
            )
def _flush_unattributed_hits(issues: list[str], bot: str, pending_hits: dict[str, list[str]]) -> None:
    for locations in pending_hits.values():
        for location in locations:
            issues.append(f"{location} {bot} bullet.hit_bot cannot be attributed to a gun mode")


def _flush_unresolved_shots(
    issues: list[str],
    bot: str,
    shots: dict[str, str],
    resolved: set[str],
    resolution_enabled_bots: set[str],
    profile_totals: dict[str, tuple[int, int]],
    round_profile_base: int,
    terminal_round: bool,
) -> None:
    if bot not in resolution_enabled_bots:
        return
    unresolved = set(shots) - resolved
    if unresolved and (
        terminal_round or _terminal_profile_covers_round(shots, profile_totals, round_profile_base)
    ):
        return
    for bullet_id in sorted(unresolved):
        issues.append(f"{bot} bullet.fired bullet_id={bullet_id} has no bullet.resolved outcome")


def _terminal_profile_covers_round(
    shots: dict[str, str],
    profile_totals: dict[str, tuple[int, int]],
    round_profile_base: int,
) -> bool:
    accepted = sum(item[0] for item in profile_totals.values())
    resolved = sum(item[1] for item in profile_totals.values())
    return accepted == resolved and accepted - round_profile_base == len(shots)


def _is_terminal_event(event: dict[str, Any], name: str, fields: dict[str, Any]) -> bool:
    state = event.get("state") if isinstance(event.get("state"), dict) else {}
    own_energy = _numeric(state.get("energy"))
    if own_energy is not None and own_energy <= 0.0:
        return True
    victim_energy = _numeric(fields.get("energy"))
    enemy_count = _whole_number(state.get("enemy_count"))
    return (
        name == "bullet.hit_bot"
        and victim_energy is not None
        and victim_energy <= 0.0
        and enemy_count is not None
        and enemy_count <= 0
    )


def _audit_combat_profile(issues: list[str], location: str, bot: str, fields: dict[str, Any]) -> None:
    for prefix in ("recent", "lifetime"):
        accepted = _numeric(fields.get(f"{prefix}_own_accepted_shots"))
        resolved = _numeric(fields.get(f"{prefix}_own_resolved_shots"))
        hits = _numeric(fields.get(f"{prefix}_own_hits"))
        misses = _numeric(fields.get(f"{prefix}_own_misses"))
        enemy_shots = _numeric(fields.get(f"{prefix}_enemy_inferred_shots"))
        weighted_enemy_shots = _numeric(fields.get(f"{prefix}_enemy_weighted_shots"))
        enemy_hits = _numeric(fields.get(f"{prefix}_enemy_hits"))
        enemy_hits_matched = _numeric(fields.get(f"{prefix}_enemy_hits_matched"))
        if None not in (resolved, hits, misses) and resolved != hits + misses:
            issues.append(f"{location} {bot} combat.profile {prefix} resolved shots do not equal hits plus misses")
        if prefix == "lifetime" and accepted is not None and resolved is not None and resolved > accepted:
            issues.append(f"{location} {bot} combat.profile lifetime resolved shots exceed accepted shots")
        if None not in (enemy_shots, weighted_enemy_shots) and weighted_enemy_shots > enemy_shots + 1e-6:
            issues.append(f"{location} {bot} combat.profile {prefix} weighted enemy shots exceed raw shots")
        if None not in (enemy_hits, enemy_hits_matched) and enemy_hits_matched > enemy_hits:
            issues.append(f"{location} {bot} combat.profile {prefix} matched enemy hits exceed enemy hits")


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _whole_number(value: object) -> int | None:
    number = _numeric(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _summary(events: list[dict[str, Any]], issues: list[str]) -> dict[str, object]:
    by_bot = Counter(str(event.get("bot") or "?") for event in events)
    by_event = Counter(str(event.get("event") or "?") for event in events)
    return {
        "events": len(events),
        "bots": dict(sorted(by_bot.items())),
        "eventCounts": dict(sorted(by_event.items())),
        "issues": issues,
    }


def _print_summary(summary: dict[str, object]) -> None:
    print(f"events: {summary['events']}")
    for bot, count in summary["bots"].items():  # type: ignore[union-attr]
        print(f"bot {bot}: {count}")
    for event, count in summary["eventCounts"].items():  # type: ignore[union-attr]
        print(f"event {event}: {count}")
    issues = summary["issues"]
    if issues:
        print("issues:")
        for issue in issues:  # type: ignore[union-attr]
            print(f"- {issue}")
    else:
        print("issues: none")


if __name__ == "__main__":
    raise SystemExit(main())
