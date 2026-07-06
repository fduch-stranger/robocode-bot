import json
import tempfile
import unittest
from pathlib import Path

from tools import radar_efficiency_summary


def event_line(bot: str, event: str, fields: dict[str, object]) -> str:
    return json.dumps({"bot": bot, "event": event, "fields": fields}) + "\n"


class RadarEfficiencySummaryTest(unittest.TestCase):
    def test_summarize_events_reports_freshness_and_fire_outcomes(self) -> None:
        events = [
            {"event": "track", "fields": {"age": 0, "radar_age": 0, "radar_mode": "lock", "hold_reason": "ready"}},
            {"event": "track", "fields": {"age": 1, "radar_age": 1, "radar_mode": "lock", "hold_reason": "ready"}},
            {"event": "track", "fields": {"age": 3, "radar_age": 3, "radar_mode": "reacquire", "hold_reason": "stale"}},
            {"event": "track", "fields": {"age": 5, "radar_age": 5, "radar_mode": "widen", "hold_reason": "stale"}},
            {"event": "bullet.fired", "fields": {"bullet_id": 1, "target_age": 0}},
            {"event": "bullet.fired", "fields": {"bullet_id": 2, "target_age": 3}},
            {"event": "bullet.fired", "fields": {"bullet_id": 3, "target_age": 5}},
            {"event": "bullet.fired", "fields": {"bullet_id": 4}},
            {"event": "bullet.hit_bot", "fields": {"bullet_id": 1}},
            {"event": "bullet.hit_bot", "fields": {"bullet_id": 2}},
            {"event": "bullet.hit_bot", "fields": {"bullet_id": 4}},
            {"event": "scan.reacquired", "fields": {"previous_age": 6}},
            {"event": "target.reacquire", "fields": {"age": 5}},
            {"event": "target.drop_lost", "fields": {"age": 10}},
            {"event": "target.stale", "fields": {"bot_id": 7}},
            {"event": "enemy.fire_detected", "fields": {"scan_gap": 2}},
            {"event": "enemy.energy_drop_ignored", "fields": {"scan_gap": 5}},
        ]

        summary = radar_efficiency_summary.summarize_events(events, telemetry_files=1)

        self.assertEqual(4, summary.trackTurns)
        self.assertEqual(2, summary.freshTargetTurns)
        self.assertEqual(2, summary.staleTargetTurns)
        self.assertEqual(1, summary.lostTargetTurns)
        self.assertEqual(0.5, summary.freshTargetRate)
        self.assertEqual({"lock": 2, "reacquire": 1, "widen": 1}, summary.radarModes)
        self.assertEqual(2, summary.staleHoldCount)
        self.assertEqual(4, summary.shots)
        self.assertEqual(1, summary.freshShots)
        self.assertEqual(2, summary.staleShots)
        self.assertEqual(1, summary.lostShots)
        self.assertEqual(1, summary.unknownAgeShots)
        self.assertEqual(3, summary.hits)
        self.assertEqual(1, summary.freshShotHits)
        self.assertEqual(1, summary.staleShotHits)
        self.assertEqual(0, summary.lostShotHits)
        self.assertEqual(1, summary.unknownAgeShotHits)
        self.assertEqual(1, summary.scanReacquiredCount)
        self.assertEqual(6, summary.scanReacquiredPreviousAge.max)
        self.assertEqual(1, summary.targetDropLostCount)
        self.assertEqual(1, summary.targetStaleCount)
        self.assertEqual(2, summary.enemyFireDetectedScanGap.max)
        self.assertEqual(5, summary.enemyEnergyDropIgnoredScanGap.max)

    def test_cli_discovers_run_telemetry_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-001"
            telemetry_dir = run_dir / "telemetry"
            telemetry_dir.mkdir(parents=True)
            telemetry_path = telemetry_dir / "adaptive.jsonl"
            json_path = root / "radar.json"
            telemetry_path.write_text(
                "".join(
                    [
                        event_line("adaptive-prime", "track", {"age": 0, "radar_mode": "lock"}),
                        event_line("adaptive-prime", "track", {"age": 4, "radar_mode": "reacquire"}),
                        event_line("chase-lock", "track", {"age": 9, "radar_mode": "widen"}),
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = radar_efficiency_summary.main(
                [str(run_dir), "--bot", "adaptive-prime", "--json-output", str(json_path)]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual("adaptive-prime", payload["bot"])
            self.assertEqual(1, payload["telemetryFiles"])
            self.assertEqual(2, payload["trackTurns"])
            self.assertEqual(1, payload["freshTargetTurns"])
            self.assertEqual(1, payload["staleTargetTurns"])

    def test_summarize_warns_when_track_events_are_missing(self) -> None:
        summary = radar_efficiency_summary.summarize_events(
            [{"event": "bullet.fired", "fields": {"bullet_id": 1, "target_age": 0}}],
            telemetry_files=1,
        )

        self.assertEqual(0, summary.trackTurns)
        self.assertEqual(
            ("no track events found; target freshness rates and radar mode distribution are unavailable",),
            summary.warnings,
        )


if __name__ == "__main__":
    unittest.main()
