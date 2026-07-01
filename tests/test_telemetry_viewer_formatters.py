import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORMATTERS = ROOT / "tools" / "telemetry_viewer" / "static" / "formatters.js"


@unittest.skipIf(shutil.which("node") is None, "node is required for telemetry viewer formatter tests")
class TelemetryViewerFormattersTest(unittest.TestCase):
    def run_js(self, expression: str):
        script = textwrap.dedent(
            f"""
            const view = require({json.dumps(str(FORMATTERS))});
            const result = {expression};
            console.log(JSON.stringify(result));
            """
        )
        completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        return json.loads(completed.stdout)

    def test_dead_energy_is_clamped_for_dashboard_display(self) -> None:
        result = self.run_js("view.displayEnergy(-2.4)")

        self.assertEqual({"value": 0, "label": "0 (dead)", "dead": True}, result)

    def test_scan_reacquired_summary_uses_named_fields(self) -> None:
        summary = self.run_js(
            """
            view.summarizeEvent({
              event: "scan.reacquired",
              fields: {bot_id: 3, previous_age: 9, previous_x: 737.7, previous_y: 493.7, x: 726.5, y: 527.4}
            })
            """
        )

        self.assertIn("target=3", summary)
        self.assertIn("age=9", summary)
        self.assertIn("current_x=726.5", summary)
        self.assertNotIn("{", summary)

    def test_lifecycle_events_have_readable_summaries(self) -> None:
        summaries = self.run_js(
            """
            ({
              stale: view.summarizeEvent({event: "target.stale", fields: {bot_id: 4, age: 12}}),
              drop: view.summarizeEvent({event: "target.drop_lost", fields: {bot_id: 5, age: 31, cached_distance: 412, known_targets: 2}}),
              reset: view.summarizeEvent({event: "round.reset", fields: {previous_turn: 41, current_turn: 1}}),
              ignored: view.summarizeEvent({event: "enemy.energy_drop_ignored", fields: {bot_id: 8, reason: "same_turn", corrected_drop: 0.4, raw_drop: 3.1, distance: 221, energy: 88}})
            })
            """
        )

        self.assertEqual("target=4 age=12", summaries["stale"])
        self.assertEqual("target=5 age=31 cached_distance=412 known_targets=2", summaries["drop"])
        self.assertEqual("previous_turn=41 current_turn=1", summaries["reset"])
        self.assertIn("target=8", summaries["ignored"])
        self.assertIn("reason=same_turn", summaries["ignored"])
        self.assertIn("drop=0.4", summaries["ignored"])

    def test_normalization_extracts_cross_bot_dashboard_fields(self) -> None:
        normalized = self.run_js(
            """
            view.normalizeEvent({
              event: "movement.minimum_risk",
              fields: {bot_id: 2, firepower: 1.6, distance: 345, mode: "minimum_risk", near_wall: true}
            })
            """
        )

        self.assertEqual(2, normalized["target"])
        self.assertEqual(1.6, normalized["power"])
        self.assertEqual(345, normalized["distance"])
        self.assertEqual("minimum_risk", normalized["movementMode"])
        self.assertTrue(normalized["wallRisk"])


if __name__ == "__main__":
    unittest.main()
