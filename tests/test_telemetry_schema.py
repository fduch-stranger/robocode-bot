import unittest

from bot_core.telemetry.schema import CANONICAL_FIELDS, EVENT_SPECS, missing_required_fields, normalize_fields


class TelemetrySchemaTest(unittest.TestCase):
    def test_canonical_fields_include_dashboard_contract(self) -> None:
        self.assertEqual(
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
            },
            set(CANONICAL_FIELDS),
        )

    def test_aliases_normalize_target_and_reason_without_mutating_raw_names(self) -> None:
        fields = normalize_fields("enemy.fire_detected", {"bot_id": 7, "power": 1.8, "distance": 240.0, "evasion": "active_duel"})
        self.assertEqual(7, fields["bot_id"])
        self.assertEqual(7, fields["target"])

        track = normalize_fields("track", {"target": 3, "firepower": 1.2, "hold_reason": "gun_alignment"})
        self.assertEqual(1.2, track["power"])
        self.assertEqual("gun_alignment", track["reason"])

    def test_gun_switch_decision_selected_is_not_normalized_as_current_mode(self) -> None:
        fields = normalize_fields("gun.switch_decision", {"selected": "dynamic_cluster", "changed": False})

        self.assertEqual("dynamic_cluster", fields["selected"])
        self.assertNotIn("aim_mode", fields)
        self.assertNotIn("gun_mode", fields)

    def test_missing_required_fields_uses_aliases(self) -> None:
        self.assertEqual((), missing_required_fields("target.select", {"selected": 2}))
        self.assertEqual(("aim_mode",), missing_required_fields("bullet.fired", {"bullet_id": 9, "power": 1.6}))

    def test_key_dashboard_events_have_specs(self) -> None:
        for event_name in (
            "track",
            "gun.switch",
            "gun.switch_decision",
            "bot.turn_timing",
            "bot.skipped_turn",
            "bullet.fired",
            "bullet.hit_bot",
            "enemy.fire_detected",
            "movement.flatten",
            "movement.flatten_shadow",
            "movement.feint",
            "movement.minimum_risk",
            "hit.bullet",
        ):
            self.assertIn(event_name, EVENT_SPECS)


if __name__ == "__main__":
    unittest.main()
