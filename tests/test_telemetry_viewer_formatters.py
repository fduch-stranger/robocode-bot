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
              config: view.summarizeEvent({event: "bot.config", fields: {selectable_guns: ["dynamic_cluster", "traditional_gf"], force_guns: ["linear", "displacement"], forced_gun: "traditional_gf", eval_waves: true}}),
              ignored: view.summarizeEvent({event: "enemy.energy_drop_ignored", fields: {bot_id: 8, reason: "same_turn", corrected_drop: 0.4, raw_drop: 3.1, distance: 221, energy: 88}})
            })
            """
        )

        self.assertEqual("target=4 age=12", summaries["stale"])
        self.assertEqual("target=5 age=31 cached_distance=412 known_targets=2", summaries["drop"])
        self.assertEqual("previous_turn=41 current_turn=1", summaries["reset"])
        self.assertIn("selectable=dynamic_cluster,traditional_gf", summaries["config"])
        self.assertIn("pinned=traditional_gf", summaries["config"])
        self.assertNotIn("force=", summaries["config"])
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

    def test_unchanged_gun_switch_decision_is_diagnostic_not_current_mode(self) -> None:
        result = self.run_js(
            """
            (() => {
              const event = {
                event: "gun.switch_decision",
                fields: {selected: "traditional_gf", changed: false, aim_mode: "traditional_gf"}
              };
              event.normalized = view.normalizeEvent(event);
              return {
                aimMode: event.normalized.aimMode,
                gunMode: view.gunModeFromEvent(event),
                normalizedGunMode: event.normalized.gunMode,
                summary: view.summarizeEvent(event)
              };
            })()
            """
        )

        self.assertIsNone(result["aimMode"])
        self.assertIsNone(result["gunMode"])
        self.assertIsNone(result["normalizedGunMode"])
        self.assertIn("switch=no", result["summary"])
        self.assertIn("current=traditional_gf", result["summary"])

    def test_changed_gun_switch_decision_can_report_selected_mode(self) -> None:
        result = self.run_js(
            """
            (() => {
              const event = {
                event: "gun.switch_decision",
                fields: {
                  target: 4,
                  previous: "linear",
                  selected: "dynamic_cluster",
                  changed: true,
                  candidates: [
                    {mode: "dynamic_cluster", available: true, score: 0.42, visits: 120, required_visits: 90, reason: "selected"}
                  ]
                }
              };
              event.normalized = view.normalizeEvent(event);
              return {
                gunMode: view.gunModeFromEvent(event),
                normalizedGunMode: event.normalized.gunMode,
                summary: view.summarizeEvent(event)
              };
            })()
            """
        )

        self.assertEqual("dynamic_cluster", result["gunMode"])
        self.assertEqual("dynamic_cluster", result["normalizedGunMode"])
        self.assertIn("switch=linear->dynamic_cluster", result["summary"])
        self.assertIn("selected=1", result["summary"])

    def test_gun_switch_decision_summary_lists_all_candidates(self) -> None:
        summary = self.run_js(
            """
            view.summarizeEvent({
              event: "gun.switch_decision",
              fields: {
                target: 1,
                previous: "linear",
                selected: "linear",
                changed: false,
                candidates: [
                  {mode: "linear", available: true, score: 0.12, visits: 80, required_visits: 65, reason: "current"},
                  {mode: "traditional_gf", available: true, score: 0.10, visits: 40, required_visits: 60, reason: "visits"},
                  {mode: "dynamic_cluster", available: true, score: 0.18, visits: 70, required_visits: 65, reason: "margin"},
                  {mode: "head_on", available: true, score: 0.08, visits: 70, required_visits: 65, reason: "source_degraded"}
                ]
              }
            })
            """
        )

        self.assertIn("blocked=2", summary)
        self.assertIn("degraded=1", summary)
        self.assertIn("visits=40/60", summary)
        self.assertIn(
            "details=[linear current score=0.1 visits=80/65; traditional_gf blocked:visits score=0.1 visits=40/60; dynamic_cluster blocked:margin score=0.2 visits=70/65; head_on source_degraded score=0.1 visits=70/65]",
            summary,
        )

    def test_gun_switch_decision_summary_caps_long_candidate_lists(self) -> None:
        summary = self.run_js(
            """
            view.summarizeEvent({
              event: "gun.switch_decision",
              fields: {
                target: 1,
                previous: "linear",
                selected: "linear",
                changed: false,
                candidates: [
                  {mode: "linear", available: true, score: 0.12, visits: 80, required_visits: 65, reason: "current"},
                  {mode: "traditional_gf", available: true, score: 0.10, visits: 40, required_visits: 60, reason: "visits"},
                  {mode: "dynamic_cluster", available: true, score: 0.18, visits: 70, required_visits: 65, reason: "margin"},
                  {mode: "head_on", available: false, score: 0.08, visits: 12, required_visits: 65, reason: "unavailable"},
                  {mode: "displacement", available: true, score: 0.06, visits: 90, required_visits: 65, reason: "score_floor"}
                ]
              }
            })
            """
        )

        self.assertIn("blocked=3", summary)
        self.assertIn("unavailable=1", summary)
        self.assertIn("+1 more", summary)
        self.assertNotIn("displacement", summary)

    def test_stream_filter_matches_event_categories(self) -> None:
        result = self.run_js(
            """
            ({
              gunSwitch: view.eventMatchesStreamFilter({event: "gun.switch"}, "gun"),
              gunWave: view.eventMatchesStreamFilter({event: "gun.wave_visit"}, "gun"),
              gunExcludesBullet: view.eventMatchesStreamFilter({event: "bullet.fired"}, "gun"),
              gunSwitchFilterIncludesSwitch: view.eventMatchesStreamFilter({event: "gun.switch"}, "gun-switch"),
              gunSwitchFilterIncludesDecision: view.eventMatchesStreamFilter({event: "gun.switch_decision"}, "gun-switch"),
              gunSwitchFilterExcludesWave: view.eventMatchesStreamFilter({event: "gun.wave_visit"}, "gun-switch"),
              movementIncludesWall: view.eventMatchesStreamFilter({event: "wall.avoid"}, "movement"),
              targetingIncludesScan: view.eventMatchesStreamFilter({event: "scan.reacquired"}, "targeting"),
              combatIncludesEnemy: view.eventMatchesStreamFilter({event: "enemy.fire_detected"}, "combat"),
              telemetryIncludesBotConfig: view.eventMatchesStreamFilter({event: "bot.config"}, "telemetry"),
              allIncludesTrack: view.eventMatchesStreamFilter({event: "track"}, "all")
            })
            """
        )

        self.assertTrue(result["gunSwitch"])
        self.assertTrue(result["gunWave"])
        self.assertFalse(result["gunExcludesBullet"])
        self.assertTrue(result["gunSwitchFilterIncludesSwitch"])
        self.assertTrue(result["gunSwitchFilterIncludesDecision"])
        self.assertFalse(result["gunSwitchFilterExcludesWave"])
        self.assertTrue(result["movementIncludesWall"])
        self.assertTrue(result["targetingIncludesScan"])
        self.assertTrue(result["combatIncludesEnemy"])
        self.assertTrue(result["telemetryIncludesBotConfig"])
        self.assertTrue(result["allIncludesTrack"])


if __name__ == "__main__":
    unittest.main()
