import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools.fire_utility_summary import main, summarize_events


def _event(name: str, **fields: object) -> dict[str, object]:
    return {"bot": "adaptive-prime", "event": name, "fields": fields}


def _accepted(
    bullet_id: int,
    q: float,
    *,
    mode: str = "linear",
    range_band: str = "mid",
    power_band: str = "medium",
    fallback: str = "global",
) -> dict[str, object]:
    return _event(
        "fire.utility_accepted",
        bullet_id=bullet_id,
        q=q,
        aim_mode=mode,
        range_band=range_band,
        power_band=power_band,
        quality_band="mature",
        fallback_level=fallback,
        calibration_support=20,
        power=1.0,
        score_utility=q * 4.0,
        energy_swing_utility=q * 7.0 - 1.0,
        reason="ready",
    )


class FireUtilitySummaryTest(unittest.TestCase):
    def test_reconciles_real_hits_and_terminal_misses(self) -> None:
        summary = summarize_events(
            [
                _event("fire.utility_opportunity", action="fire", reason="ready"),
                _event("fire.utility_opportunity", action="hold", reason="gun_alignment"),
                _event("bullet.fired", bullet_id=1),
                _accepted(1, 0.2, range_band="near", power_band="low"),
                _event("bullet.hit_bot", bullet_id=1, damage=4.0),
                _event("fire.utility_outcome", bullet_id=1, outcome="hit_bot", hit=True),
                _event("bullet.fired", bullet_id=2),
                _accepted(2, 0.4, range_band="far", power_band="high"),
            ]
        )

        self.assertEqual(2, summary["acceptedShots"])
        self.assertEqual(1.0, summary["acceptedCoverage"])
        self.assertEqual(1, summary["overall"]["hits"])
        self.assertAlmostEqual(0.3, summary["overall"]["predictedHitRate"])
        self.assertAlmostEqual(0.5, summary["overall"]["observedHitRate"])
        self.assertEqual(1, summary["byRangeBand"]["near"]["hits"])
        self.assertEqual(0, summary["byRangeBand"]["far"]["hits"])
        self.assertEqual(1, summary["opportunities"]["fire"])
        self.assertEqual(1, summary["opportunities"]["hold"])
        diagnostics = summary["calibrationDiagnostics"]
        self.assertEqual(2, diagnostics["supportedShots"])
        self.assertEqual(1.0, diagnostics["supportedCoverage"])
        self.assertAlmostEqual(13.0 / 36.0, diagnostics["fixedPriorBrierScore"])
        self.assertAlmostEqual(-7.0 / 65.0, diagnostics["brierSkillVsFixedPrior"])
        self.assertAlmostEqual(0.6, diagnostics["expectedCalibrationError"])
        self.assertAlmostEqual(-0.2, diagnostics["hitMissProbabilitySeparation"])

    def test_bullet_ids_are_scoped_by_round_and_corrections_override_misses(self) -> None:
        summary = summarize_events(
            [
                _event("bullet.fired", bullet_id=1),
                _accepted(1, 0.1),
                _event("fire.utility_outcome", bullet_id=1, outcome="round_end", hit=False),
                _event(
                    "fire.utility_outcome_corrected",
                    bullet_id=1,
                    previous_outcome="round_end",
                    outcome="hit_bot",
                    hit=True,
                ),
                _event("round.reset"),
                _event("bullet.fired", bullet_id=1),
                _accepted(1, 0.2),
                _event("fire.utility_outcome", bullet_id=1, outcome="hit_wall", hit=False),
            ]
        )

        self.assertEqual(2, summary["acceptedShots"])
        self.assertEqual(1, summary["overall"]["hits"])
        self.assertEqual(1, summary["utilityCorrections"])
        self.assertEqual(1.0, summary["utilityResolutionCoverage"])

    def test_ignores_corrections_without_an_eligible_round_end_outcome(self) -> None:
        summary = summarize_events(
            [
                _event("bullet.fired", bullet_id=1),
                _accepted(1, 0.2),
                _event("fire.utility_outcome", bullet_id=1, outcome="hit_wall", hit=False),
                _event(
                    "fire.utility_outcome_corrected",
                    bullet_id=1,
                    previous_outcome="hit_wall",
                    outcome="hit_bot",
                    hit=True,
                ),
                _event("bullet.fired", bullet_id=2),
                _accepted(2, 0.3),
                _event(
                    "fire.utility_outcome_corrected",
                    bullet_id=2,
                    previous_outcome="round_end",
                    outcome="hit_bot",
                    hit=True,
                ),
            ]
        )

        self.assertEqual(0, summary["overall"]["hits"])
        self.assertEqual(2, summary["utilityCorrections"])
        self.assertIn("invalid utility corrections: 2", summary["warnings"])

    def test_cli_writes_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            telemetry_dir = Path(directory)
            events = [
                _event("bullet.fired", bullet_id=1),
                _accepted(1, 0.25),
                _event("bullet.hit_bot", bullet_id=1, damage=4.0),
            ]
            (telemetry_dir / "adaptive-prime.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            output = telemetry_dir / "summary.json"
            with patch(
                "sys.argv",
                [
                    "fire_utility_summary.py",
                    str(telemetry_dir),
                    "--json-output",
                    str(output),
                ],
            ):
                self.assertEqual(0, main())
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, data["acceptedShots"])
            self.assertEqual(1, data["overall"]["hits"])
            self.assertIn("calibrationDiagnostics", data)

    def test_cli_reports_malformed_jsonl_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            telemetry_dir = Path(directory)
            path = telemetry_dir / "adaptive-prime.jsonl"
            path.write_text('{"bot": "adaptive-prime"', encoding="utf-8")
            stderr = StringIO()

            with patch("sys.argv", ["fire_utility_summary.py", str(telemetry_dir)]):
                with redirect_stderr(stderr):
                    exit_code = main()

        self.assertEqual(2, exit_code)
        self.assertIn("adaptive-prime.jsonl:1", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
