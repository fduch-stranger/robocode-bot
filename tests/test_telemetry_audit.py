import unittest

from tools.telemetry_audit import _audit


class TelemetryAuditTest(unittest.TestCase):
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
