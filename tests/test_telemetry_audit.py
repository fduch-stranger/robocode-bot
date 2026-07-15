import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools.telemetry_audit import _audit, main


def _utility_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "action": "fire",
        "reason": "ready",
        "aim_mode": "linear",
        "distance": 400.0,
        "range_band": "mid",
        "power_band": "medium",
        "quality_band": "mature",
        "solution_quality": 0.15,
        "model_support": 40,
        "q": 0.166667,
        "calibration_support": 0,
        "calibration_hits": 0,
        "fallback_level": "global_prior",
        "power": 1.0,
        "bullet_damage": 4.0,
        "hit_bonus": 3.0,
        "gun_heat": 1.2,
        "cooling_rate": 0.1,
        "cooldown_turns": 12,
        "score_utility": 0.666667,
        "energy_swing_utility": 0.166667,
    }
    fields.update(overrides)
    return fields


class TelemetryAuditTest(unittest.TestCase):
    def test_cli_writes_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry_dir = Path(temp_dir) / "telemetry"
            telemetry_dir.mkdir()
            output_path = Path(temp_dir) / "audit.json"
            (telemetry_dir / "adaptive-prime.jsonl").write_text(
                json.dumps({"bot": "adaptive-prime", "event": "custom.event", "fields": {}}) + "\n",
                encoding="utf-8",
            )

            with patch(
                "sys.argv",
                [
                    "telemetry_audit.py",
                    str(telemetry_dir),
                    "--require-bot",
                    "adaptive-prime",
                    "--json-output",
                    str(output_path),
                ],
            ):
                with redirect_stdout(StringIO()):
                    exit_code = main()

            summary = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual(1, summary["events"])
        self.assertEqual({"adaptive-prime": 1}, summary["bots"])
        self.assertEqual({"custom.event": 1}, summary["eventCounts"])
        self.assertEqual([], summary["issues"])

    def test_reports_missing_required_fields_from_schema(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2},
                    "file": "adaptive.jsonl",
                    "line": 1,
                }
            ],
            [],
        )

        self.assertEqual(["adaptive.jsonl:1 adaptive-prime bullet.fired missing aim_mode"], issues)

    def test_reports_bullet_mode_mismatch(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.hit_bot",
                    "fields": {"bullet_id": 1, "power": 1.2, "damage": 4.0, "energy": 50.0, "aim_mode": "head_on"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
            ],
            [],
        )

        self.assertEqual(
            ["adaptive.jsonl:2 adaptive-prime bullet.hit_bot aim_mode=head_on does not match fired aim_mode=linear"],
            issues,
        )

    def test_attributes_bullet_hit_when_fired_event_appears_later(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.hit_bot",
                    "fields": {"bullet_id": 1, "power": 1.2, "damage": 4.0, "energy": 50.0},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
            ],
            [],
        )

        self.assertEqual([], issues)

    def test_reports_later_fired_mismatch_when_hit_appears_first(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.hit_bot",
                    "fields": {"bullet_id": 1, "power": 1.2, "damage": 4.0, "energy": 50.0, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
            ],
            [],
        )

        self.assertEqual(
            ["adaptive.jsonl:1 adaptive-prime bullet.hit_bot aim_mode=linear does not match fired aim_mode=dynamic_cluster"],
            issues,
        )

    def test_does_not_compare_reused_bullet_ids_across_rounds(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.hit_bot",
                    "fields": {"bullet_id": 1, "power": 1.2, "damage": 4.0, "energy": 50.0, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "round.reset",
                    "fields": {"previous_turn": 120, "current_turn": 1},
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 4,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.hit_bot",
                    "fields": {"bullet_id": 1, "power": 1.2, "damage": 4.0, "energy": 50.0, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 5,
                },
            ],
            [],
        )

        self.assertEqual([], issues)

    def test_reports_unattributed_bullet_hit_without_hit_or_fired_mode(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.hit_bot",
                    "fields": {"bullet_id": 1, "power": 1.2, "damage": 4.0, "energy": 50.0},
                    "file": "adaptive.jsonl",
                    "line": 1,
                }
            ],
            [],
        )

        self.assertEqual(["adaptive.jsonl:1 adaptive-prime bullet.hit_bot cannot be attributed to a gun mode"], issues)

    def test_reports_invalid_enemy_fire_evasion_label(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "enemy.fire_detected",
                    "fields": {"power": 1.5, "distance": 250.0, "evasion": "dodging"},
                    "file": "adaptive.jsonl",
                    "line": 3,
                }
            ],
            [],
        )

        self.assertEqual(["adaptive.jsonl:3 adaptive-prime enemy.fire_detected has unexpected evasion='dodging'"], issues)

    def test_audits_complete_bullet_resolution_lifecycle(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear", "outcome": "hit_wall"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
            ],
            [],
        )

        self.assertEqual([], issues)

    def test_reports_missing_duplicate_and_mismatched_bullet_resolutions(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 2, "power": 1.2, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "dynamic_cluster", "outcome": "hit_wall"},
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {"bullet_id": 1, "power": 1.2, "aim_mode": "linear", "outcome": "hit_wall"},
                    "file": "adaptive.jsonl",
                    "line": 4,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "round.reset",
                    "fields": {},
                    "file": "adaptive.jsonl",
                    "line": 5,
                },
            ],
            [],
        )

        self.assertEqual(
            [
                "adaptive.jsonl:3 adaptive-prime bullet.resolved aim_mode=dynamic_cluster does not match fired aim_mode=linear",
                "adaptive.jsonl:4 adaptive-prime bullet.resolved duplicates bullet_id=1",
                "adaptive-prime bullet.fired bullet_id=2 has no bullet.resolved outcome",
            ],
            issues,
        )

    def test_accepts_late_hit_resolution_correction(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 0.7, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {"bullet_id": 1, "power": 0.7, "aim_mode": "dynamic_cluster", "outcome": "round_end"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolution_corrected",
                    "fields": {
                        "bullet_id": 1,
                        "power": 0.7,
                        "aim_mode": "dynamic_cluster",
                        "outcome": "hit_bot",
                        "previous_outcome": "round_end",
                    },
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
            ],
            [],
        )

        self.assertEqual([], issues)

    def test_rejects_late_hit_correction_of_durable_miss(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 1.0, "aim_mode": "linear"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "fire.utility_accepted",
                    "fields": _utility_fields(bullet_id=1),
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {
                        "bullet_id": 1,
                        "power": 1.0,
                        "aim_mode": "linear",
                        "outcome": "hit_wall",
                    },
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "fire.utility_outcome",
                    "fields": _utility_fields(
                        bullet_id=1,
                        outcome="hit_wall",
                        hit=False,
                        damage=0.0,
                    ),
                    "file": "adaptive.jsonl",
                    "line": 4,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolution_corrected",
                    "fields": {
                        "bullet_id": 1,
                        "power": 1.0,
                        "aim_mode": "linear",
                        "outcome": "hit_bot",
                        "previous_outcome": "hit_wall",
                    },
                    "file": "adaptive.jsonl",
                    "line": 5,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "fire.utility_outcome_corrected",
                    "fields": _utility_fields(
                        bullet_id=1,
                        outcome="hit_bot",
                        previous_outcome="hit_wall",
                        hit=True,
                        damage=4.0,
                    ),
                    "file": "adaptive.jsonl",
                    "line": 6,
                },
            ],
            [],
        )

        self.assertTrue(
            any(
                "bullet.resolution_corrected is not a round_end-to-hit_bot correction"
                in issue
                for issue in issues
            )
        )
        self.assertTrue(
            any(
                "fire.utility_outcome_corrected is not a round_end-to-hit_bot correction"
                in issue
                for issue in issues
            )
        )

    def test_accepts_complete_terminal_profile_before_truncated_resolution_events(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 0.7, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 2, "power": 0.7, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "combat.profile",
                    "fields": {
                        "version": 1,
                        "target": 2,
                        "recent_window_start": 1,
                        "recent_window_end": 20,
                        "lifetime_own_accepted_shots": 2,
                        "lifetime_own_resolved_shots": 2,
                        "lifetime_own_hits": 0,
                        "lifetime_own_misses": 2,
                    },
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {
                        "bullet_id": 1,
                        "power": 0.7,
                        "aim_mode": "dynamic_cluster",
                        "outcome": "round_end",
                    },
                    "file": "adaptive.jsonl",
                    "line": 4,
                },
            ],
            [],
        )

        self.assertEqual([], issues)

    def test_accepts_unattributed_profile_for_complete_terminal_accounting(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 0.7, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 2, "power": 0.7, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "combat.profile",
                    "fields": {
                        "version": 1,
                        "target": None,
                        "recent_window_start": 1,
                        "recent_window_end": 20,
                        "lifetime_own_accepted_shots": 2,
                        "lifetime_own_resolved_shots": 2,
                        "lifetime_own_hits": 0,
                        "lifetime_own_misses": 2,
                    },
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {
                        "bullet_id": 2,
                        "power": 0.7,
                        "aim_mode": "dynamic_cluster",
                        "outcome": "round_end",
                    },
                    "file": "adaptive.jsonl",
                    "line": 4,
                },
            ],
            [],
        )

        self.assertEqual([], issues)

    def test_accepts_in_flight_bullets_at_terminal_death_eof(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "power": 0.7, "aim_mode": "dynamic_cluster"},
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "bullet.resolved",
                    "fields": {
                        "bullet_id": 2,
                        "power": 0.7,
                        "aim_mode": "dynamic_cluster",
                        "outcome": "hit_wall",
                    },
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "hit.bullet",
                    "fields": {"owner": 2, "power": 1.9, "damage": 9.4, "energy": -1.3},
                    "state": {"energy": -1.3},
                    "file": "adaptive.jsonl",
                    "line": 3,
                },
            ],
            [],
        )

        self.assertEqual(
            ["adaptive.jsonl:2 adaptive-prime bullet.resolved has no accepted bullet.fired for bullet_id=2"],
            issues,
        )

    def test_reports_inconsistent_combat_profile_totals(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "combat.profile",
                    "fields": {
                        "version": 1,
                        "target": 2,
                        "recent_window_start": 1,
                        "recent_window_end": 20,
                        "lifetime_own_accepted_shots": 2,
                        "lifetime_own_resolved_shots": 3,
                        "lifetime_own_hits": 1,
                        "lifetime_own_misses": 1,
                        "lifetime_enemy_inferred_shots": 2,
                        "lifetime_enemy_weighted_shots": 2.5,
                        "lifetime_enemy_hits": 1,
                        "lifetime_enemy_hits_matched": 2,
                    },
                    "file": "adaptive.jsonl",
                    "line": 5,
                }
            ],
            [],
        )

        self.assertEqual(4, len(issues))
        self.assertTrue(any("resolved shots do not equal hits plus misses" in issue for issue in issues))
        self.assertTrue(any("resolved shots exceed accepted shots" in issue for issue in issues))
        self.assertTrue(any("weighted enemy shots exceed raw shots" in issue for issue in issues))
        self.assertTrue(any("matched enemy hits exceed enemy hits" in issue for issue in issues))

    def test_reports_invalid_movement_evidence_semantics(self) -> None:
        issues = _audit(
            [
                {
                    "bot": "adaptive-prime",
                    "event": "movement.profile_visit",
                    "fields": {
                        "evidence_kind": "expected_expired",
                        "wave_kind": "expected",
                        "occupancy_visits": 1.0,
                    },
                    "file": "adaptive.jsonl",
                    "line": 1,
                },
                {
                    "bot": "adaptive-prime",
                    "event": "movement.evidence_shadow",
                    "fields": {
                        "live_direction": 1,
                        "shadow_direction": -1,
                        "hit_fallback_level": "global",
                        "score_source": "legacy",
                        "current_hit_danger": -0.1,
                    },
                    "file": "adaptive.jsonl",
                    "line": 2,
                },
            ],
            [],
        )

        self.assertEqual(
            [
                "adaptive.jsonl:1 adaptive-prime expired expected wave persisted occupancy evidence",
                "adaptive.jsonl:2 adaptive-prime movement.evidence_shadow has unexpected fallback='global'",
                "adaptive.jsonl:2 adaptive-prime movement.evidence_shadow has negative current_hit_danger",
            ],
            issues,
        )

    def test_audits_complete_fire_utility_lifecycle(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "bot.config",
                "fields": {"fire_utility_shadow": True},
                "file": "adaptive.jsonl",
                "line": 1,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_opportunity",
                "fields": _utility_fields(),
                "file": "adaptive.jsonl",
                "line": 2,
            },
            {
                "bot": "adaptive-prime",
                "event": "bullet.fired",
                "fields": {"bullet_id": 1, "power": 1.0, "aim_mode": "linear"},
                "file": "adaptive.jsonl",
                "line": 3,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_accepted",
                "fields": _utility_fields(bullet_id=1),
                "file": "adaptive.jsonl",
                "line": 4,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_outcome",
                "fields": _utility_fields(
                    bullet_id=1,
                    outcome="hit_wall",
                    hit=False,
                    damage=0.0,
                ),
                "file": "adaptive.jsonl",
                "line": 5,
            },
        ]

        self.assertEqual([], _audit(events, []))

    def test_accepts_dynamic_high_quality_odds_adjustment(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_opportunity",
                "fields": _utility_fields(
                    action="hold",
                    reason="gun_alignment",
                    aim_mode="dynamic_cluster",
                    solution_quality=0.10,
                    quality_band="high",
                    q=0.259259,
                    fallback_level="dynamic_quality_prior",
                    score_utility=1.037037,
                    energy_swing_utility=0.814813,
                ),
                "file": "adaptive.jsonl",
                "line": 1,
            },
        ]

        self.assertEqual([], _audit(events, []))

    def test_reports_invalid_fire_utility_math_and_missing_attribution(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "bot.config",
                "fields": {"fire_utility_shadow": True},
                "file": "adaptive.jsonl",
                "line": 1,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_opportunity",
                "fields": _utility_fields(
                    action="hold",
                    reason="ready",
                    q=1.2,
                    bullet_damage=5.0,
                    score_utility=6.0,
                    cooldown_turns=10,
                ),
                "file": "adaptive.jsonl",
                "line": 2,
            },
            {
                "bot": "adaptive-prime",
                "event": "bullet.fired",
                "fields": {"bullet_id": 1, "power": 1.0, "aim_mode": "linear"},
                "file": "adaptive.jsonl",
                "line": 3,
            },
        ]

        issues = _audit(events, [])

        self.assertTrue(any("q is outside" in issue for issue in issues))
        self.assertTrue(any("bullet_damage=5.0" in issue for issue in issues))
        self.assertTrue(any("cooldown_turns=10" in issue for issue in issues))
        self.assertTrue(any("holds with fire reason" in issue for issue in issues))
        self.assertTrue(any("has no fire.utility_accepted" in issue for issue in issues))

    def test_reports_fire_utility_posterior_and_future_support_leakage(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_opportunity",
                "fields": _utility_fields(
                    q=0.9,
                    calibration_support=0,
                    calibration_hits=0,
                    fallback_level="global_prior",
                    score_utility=3.6,
                    energy_swing_utility=5.3,
                ),
                "file": "adaptive.jsonl",
                "line": 1,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_opportunity",
                "fields": _utility_fields(
                    q=0.1,
                    calibration_support=4,
                    calibration_hits=0,
                    fallback_level="global",
                    score_utility=0.4,
                    energy_swing_utility=-0.3,
                ),
                "file": "adaptive.jsonl",
                "line": 2,
            },
        ]

        issues = _audit(events, [])

        self.assertTrue(any("q=0.9 does not match posterior" in issue for issue in issues))
        self.assertTrue(any("calibration_support=4 exceeds prior resolved outcomes=0" in issue for issue in issues))

    def test_reports_fire_utility_shot_without_nonterminal_outcome(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "bullet.fired",
                "fields": {"bullet_id": 1, "power": 1.0, "aim_mode": "linear"},
                "file": "adaptive.jsonl",
                "line": 1,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_accepted",
                "fields": _utility_fields(bullet_id=1),
                "file": "adaptive.jsonl",
                "line": 2,
            },
            {
                "bot": "adaptive-prime",
                "event": "round.reset",
                "fields": {},
                "file": "adaptive.jsonl",
                "line": 3,
            },
        ]

        issues = _audit(events, [])

        self.assertTrue(any("has no utility outcome" in issue for issue in issues))

    def test_reports_unresolved_positive_energy_shot_at_eof(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "bullet.fired",
                "fields": {"bullet_id": 1, "power": 1.0, "aim_mode": "linear"},
                "state": {"energy": 50.0, "enemy_count": 1},
                "file": "adaptive.jsonl",
                "line": 1,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_accepted",
                "fields": _utility_fields(bullet_id=1),
                "state": {"energy": 50.0, "enemy_count": 1},
                "file": "adaptive.jsonl",
                "line": 2,
            },
            {
                "bot": "adaptive-prime",
                "event": "bullet.resolved",
                "fields": {
                    "bullet_id": 99,
                    "power": 1.0,
                    "aim_mode": "linear",
                    "outcome": "hit_wall",
                },
                "state": {"energy": 50.0, "enemy_count": 1},
                "file": "adaptive.jsonl",
                "line": 3,
            },
        ]

        issues = _audit(events, [])

        self.assertTrue(any("bullet_id=1 has no bullet.resolved outcome" in issue for issue in issues))
        self.assertTrue(any("bullet_id=1" in issue and "has no utility outcome" in issue for issue in issues))

    def test_melee_kill_does_not_make_the_round_terminal(self) -> None:
        events = [
            {
                "bot": "adaptive-prime",
                "event": "bullet.fired",
                "fields": {"bullet_id": 1, "power": 1.0, "aim_mode": "linear"},
                "file": "adaptive.jsonl",
                "line": 1,
            },
            {
                "bot": "adaptive-prime",
                "event": "fire.utility_accepted",
                "fields": _utility_fields(bullet_id=1),
                "file": "adaptive.jsonl",
                "line": 2,
            },
            {
                "bot": "adaptive-prime",
                "event": "bullet.hit_bot",
                "fields": {
                    "bullet_id": 1,
                    "power": 1.0,
                    "damage": 4.0,
                    "energy": 0.0,
                    "aim_mode": "linear",
                },
                "state": {"energy": 50.0, "enemy_count": 1},
                "file": "adaptive.jsonl",
                "line": 3,
            },
            {
                "bot": "adaptive-prime",
                "event": "bullet.resolved",
                "fields": {
                    "bullet_id": 99,
                    "power": 1.0,
                    "aim_mode": "linear",
                    "outcome": "hit_wall",
                },
                "file": "adaptive.jsonl",
                "line": 4,
            },
            {
                "bot": "adaptive-prime",
                "event": "round.reset",
                "fields": {},
                "file": "adaptive.jsonl",
                "line": 5,
            },
        ]

        issues = _audit(events, [])

        self.assertTrue(any("bullet_id=1 has no bullet.resolved outcome" in issue for issue in issues))
        self.assertTrue(any("bullet_id=1" in issue and "has no utility outcome" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
