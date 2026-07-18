import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools.telemetry_audit import _audit, main


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


if __name__ == "__main__":
    unittest.main()
