import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools.fire_utility_replay import main, replay_events, replay_telemetry_dirs


def _event(name: str, turn: int, **fields: object) -> dict[str, object]:
    return {
        "bot": "adaptive-prime",
        "event": name,
        "turn": turn,
        "fields": fields,
    }


def _opportunity(
    turn: int,
    *,
    action: str = "fire",
    mode: str = "dynamic_cluster",
    quality: float = 0.10,
) -> dict[str, object]:
    return _event(
        "fire.utility_opportunity",
        turn,
        action=action,
        reason="ready" if action == "fire" else "gun_alignment",
        target=1,
        aim_mode=mode,
        distance=400.0,
        power=1.0,
        solution_quality=quality,
        model_support=40,
        cooling_rate=0.1,
    )


def _accepted(
    turn: int,
    bullet_id: int,
    *,
    mode: str = "dynamic_cluster",
    quality: float = 0.10,
) -> dict[str, object]:
    return _event(
        "fire.utility_accepted",
        turn,
        bullet_id=bullet_id,
        target=1,
        aim_mode=mode,
        distance=400.0,
        power=1.0,
        solution_quality=quality,
        model_support=40,
        cooling_rate=0.1,
        reason="ready",
    )


class FireUtilityReplayTest(unittest.TestCase):
    def test_replays_staged_quality_snapshot_across_later_hold(self) -> None:
        summary = replay_events(
            [
                _opportunity(1),
                _opportunity(2, action="hold"),
                _event("bullet.fired", 2, bullet_id=1),
                _accepted(2, 1),
                _event(
                    "fire.utility_outcome",
                    10,
                    bullet_id=1,
                    outcome="hit_wall",
                    hit=False,
                    damage=0.0,
                ),
                _event("round.reset", 11),
                _opportunity(1),
                _event("bullet.fired", 1, bullet_id=1),
                _accepted(1, 1),
                _event("bullet.hit_bot", 8, bullet_id=1, damage=4.0),
                _event(
                    "fire.utility_outcome",
                    8,
                    bullet_id=1,
                    outcome="hit_bot",
                    hit=True,
                    damage=4.0,
                ),
            ]
        )

        self.assertEqual(2, summary["acceptedShots"])
        self.assertEqual(1, summary["overall"]["hits"])
        self.assertEqual(
            {"dynamic_quality": 1, "dynamic_quality_prior": 1},
            summary["fallbackCounts"],
        )
        prior_adjusted = 0.35 / 1.35
        supported_adjusted = 0.25 / 1.1071428571428572
        self.assertAlmostEqual(
            (prior_adjusted + supported_adjusted) / 2.0,
            summary["overall"]["predictedHitRate"],
        )
        self.assertEqual(0.5, summary["calibrationDiagnostics"]["supportedCoverage"])

    def test_low_dynamic_quality_uses_unadjusted_global_prior(self) -> None:
        summary = replay_events(
            [
                _opportunity(1, quality=0.099),
                _event("bullet.fired", 1, bullet_id=1),
                _accepted(1, 1, quality=0.099),
                _event(
                    "fire.utility_outcome",
                    8,
                    bullet_id=1,
                    outcome="hit_wall",
                    hit=False,
                    damage=0.0,
                ),
            ]
        )

        self.assertEqual({"global_prior": 1}, summary["fallbackCounts"])
        self.assertAlmostEqual(1.0 / 6.0, summary["overall"]["predictedHitRate"])

    def test_durable_hit_without_derived_outcome_trains_the_next_round_once(self) -> None:
        summary = replay_events(
            [
                _opportunity(1, quality=0.099),
                _event("bullet.fired", 1, bullet_id=1),
                _accepted(1, 1, quality=0.099),
                _event("bullet.hit_bot", 8, bullet_id=1, damage=4.0),
                _event("round.reset", 9),
                _opportunity(1, quality=0.099),
                _event("bullet.fired", 1, bullet_id=1),
                _accepted(1, 1, quality=0.099),
                _event(
                    "fire.utility_outcome",
                    8,
                    bullet_id=1,
                    outcome="hit_wall",
                    hit=False,
                    damage=0.0,
                ),
            ]
        )

        self.assertEqual(2, summary["acceptedShots"])
        self.assertEqual(1, summary["overall"]["hits"])
        self.assertEqual({"global": 1, "global_prior": 1}, summary["fallbackCounts"])
        self.assertAlmostEqual(
            ((1.0 / 6.0) + (2.0 / 7.0)) / 2.0,
            summary["overall"]["predictedHitRate"],
        )
        self.assertEqual(0.5, summary["calibrationDiagnostics"]["supportedCoverage"])

    def test_aggregates_independently_reset_telemetry_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            telemetry_dirs = [root / "run-a", root / "run-b"]
            for index, telemetry_dir in enumerate(telemetry_dirs, start=1):
                telemetry_dir.mkdir()
                events = [
                    _opportunity(1, quality=0.099),
                    _event("bullet.fired", 1, bullet_id=index),
                    _accepted(1, index, quality=0.099),
                    _event(
                        "fire.utility_outcome",
                        8,
                        bullet_id=index,
                        outcome="hit_wall",
                        hit=False,
                        damage=0.0,
                    ),
                ]
                (telemetry_dir / "adaptive.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events),
                    encoding="utf-8",
                )

            result = replay_telemetry_dirs(telemetry_dirs, "adaptive-prime")

        self.assertEqual(2, len(result["runs"]))
        self.assertEqual(2, result["aggregate"]["acceptedShots"])
        self.assertAlmostEqual(
            1.0 / 6.0,
            result["aggregate"]["overall"]["predictedHitRate"],
        )

    def test_cli_reports_malformed_jsonl_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry_dir = Path(temp_dir)
            path = telemetry_dir / "adaptive.jsonl"
            path.write_text('{"bot": "adaptive-prime"', encoding="utf-8")
            stderr = StringIO()

            with patch("sys.argv", ["fire_utility_replay.py", str(telemetry_dir)]):
                with redirect_stderr(stderr):
                    exit_code = main()

        self.assertEqual(2, exit_code)
        self.assertIn("adaptive.jsonl:1", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
