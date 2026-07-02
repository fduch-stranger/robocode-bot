import unittest
from contextlib import redirect_stdout
from io import StringIO

from tools.gun_eval_summary import _print_summary, summarize_events


class GunEvalSummaryTest(unittest.TestCase):
    def test_summarizes_real_fire_and_eval_wave_scores(self) -> None:
        summary = summarize_events(
            [
                {"event": "bullet.fired", "fields": {"aim_mode": "linear"}},
                {"event": "bullet.fired", "fields": {"aim_mode": "linear"}},
                {"event": "bullet.hit_bot", "fields": {"aim_mode": "linear"}},
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "selected_gun": "linear",
                        "virtual_scores": {"linear": 0.5, "dynamic_cluster": 0.25},
                    },
                },
                {
                    "event": "gun.eval_wave_visit",
                    "fields": {
                        "selected_gun": "dynamic_cluster",
                        "virtual_scores": {"linear": 0.0, "dynamic_cluster": 1.0},
                    },
                },
            ]
        )

        self.assertEqual({"linear": 2}, summary["fired"])
        self.assertEqual({"linear": 1}, summary["hits"])
        self.assertEqual({"linear": 0.5}, summary["hit_rate"])
        self.assertEqual({"linear": 1}, summary["wave_selected"])
        self.assertEqual({"dynamic_cluster": 1}, summary["eval_selected"])
        self.assertEqual({"dynamic_cluster": 0.25, "linear": 0.5}, summary["wave_avg"])
        self.assertEqual({"dynamic_cluster": 1.0, "linear": 0.0}, summary["eval_avg"])

    def test_summarizes_post_switch_calibration_by_target_and_mode(self) -> None:
        summary = summarize_events(
            [
                {
                    "event": "gun.switch_decision",
                    "turn": 40,
                    "fields": {
                        "target": 9,
                        "changed": True,
                        "selected": "dynamic_cluster",
                        "candidates": [
                            {
                                "mode": "dynamic_cluster",
                                "score": 0.38,
                                "raw_score": 0.42,
                                "confidence_penalty": 0.04,
                                "current_score": 0.2,
                                "raw_current_score": 0.2,
                                "visits": 120,
                            }
                        ],
                    },
                },
                {"event": "bullet.fired", "fields": {"bullet_id": 1, "aim_mode": "dynamic_cluster"}},
                {"event": "bullet.hit_bot", "fields": {"bullet_id": 1}},
                {"event": "bullet.fired", "fields": {"bullet_id": 2, "aim_mode": "dynamic_cluster"}},
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "target": 9,
                        "selected_gun": "dynamic_cluster",
                        "virtual_scores": {"dynamic_cluster": 0.5},
                    },
                },
                {
                    "event": "gun.eval_wave_visit",
                    "fields": {
                        "target": 9,
                        "selected_gun": "dynamic_cluster",
                        "virtual_scores": {"dynamic_cluster": 0.7},
                    },
                },
            ],
            post_switch_shots=2,
        )

        calibration = summary["calibration"]["9"]["dynamic_cluster"]  # type: ignore[index]
        self.assertEqual(1, calibration["switches"])
        self.assertEqual(0.38, calibration["avg_score_at_switch"])
        self.assertEqual(0.42, calibration["avg_raw_score_at_switch"])
        self.assertEqual(0.04, calibration["avg_confidence_penalty"])
        self.assertEqual(120.0, calibration["avg_visits_at_switch"])
        self.assertEqual(2, calibration["post_switch_shots"])
        self.assertEqual(1, calibration["post_switch_hits"])
        self.assertEqual(0.5, calibration["post_switch_hit_rate"])
        self.assertEqual(-0.12, calibration["score_hit_gap"])
        self.assertEqual(-0.08, calibration["raw_score_hit_gap"])
        self.assertEqual(0.5, calibration["production_wave_avg"])
        self.assertEqual(0.0, calibration["production_hit_gap"])
        self.assertEqual(0.7, calibration["eval_avg"])
        self.assertEqual(0.2, calibration["eval_hit_gap"])

    def test_attributes_hit_before_fired_by_bullet_id(self) -> None:
        summary = summarize_events(
            [
                {"event": "bullet.hit_bot", "fields": {"bullet_id": 7}},
                {"event": "bullet.fired", "fields": {"bullet_id": 7, "aim_mode": "dynamic_cluster"}},
            ]
        )

        self.assertEqual({"dynamic_cluster": 1}, summary["fired"])
        self.assertEqual({"dynamic_cluster": 1}, summary["hits"])
        self.assertEqual({"dynamic_cluster": 1.0}, summary["hit_rate"])

    def test_hit_before_fired_does_not_cross_round_reset(self) -> None:
        summary = summarize_events(
            [
                {"event": "bullet.hit_bot", "fields": {"bullet_id": 4}},
                {"event": "round.reset", "fields": {"previous_turn": 80, "current_turn": 0}},
                {"event": "bullet.fired", "fields": {"bullet_id": 4, "aim_mode": "linear"}},
            ]
        )

        self.assertEqual({"linear": 1}, summary["fired"])
        self.assertEqual({}, summary["hits"])
        self.assertEqual({"linear": 0.0}, summary["hit_rate"])

    def test_print_summary_includes_selected_counts(self) -> None:
        stream = StringIO()
        summary = {
            "fired": {},
            "hits": {},
            "hit_rate": {},
            "wave_selected": {"linear": 2},
            "eval_selected": {"dynamic_cluster": 3},
            "wave_avg": {},
            "eval_avg": {},
            "wave_count": {},
            "eval_count": {},
            "calibration": {"2": {"linear": {"post_switch_hit_rate": 0.5}}},
        }

        with redirect_stdout(stream):
            _print_summary(summary)

        output = stream.getvalue()
        self.assertIn("wave_selected: {'linear': 2}", output)
        self.assertIn("eval_selected: {'dynamic_cluster': 3}", output)
        self.assertIn("calibration:", output)


if __name__ == "__main__":
    unittest.main()
