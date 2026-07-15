import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tools.gun_eval_summary import _print_summary, main, summarize_events


class GunEvalSummaryTest(unittest.TestCase):
    def test_cli_writes_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry_dir = Path(temp_dir) / "telemetry"
            telemetry_dir.mkdir()
            output_path = Path(temp_dir) / "summary.json"
            (telemetry_dir / "adaptive-prime.jsonl").write_text(
                json.dumps({"bot": "adaptive-prime", "event": "bullet.fired", "fields": {"aim_mode": "linear"}})
                + "\n",
                encoding="utf-8",
            )

            with patch("sys.argv", ["gun_eval_summary.py", str(telemetry_dir), "--json-output", str(output_path)]):
                with redirect_stdout(StringIO()):
                    exit_code = main()

            summary = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual({"linear": 1}, summary["fired"])

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
        self.assertEqual({"linear": 0.5}, summary["wave_selected_avg"])
        self.assertEqual({"dynamic_cluster": 0.25}, summary["wave_non_selected_avg"])
        self.assertEqual({"dynamic_cluster": 1.0}, summary["eval_selected_avg"])
        self.assertEqual({"linear": 0.0}, summary["eval_non_selected_avg"])

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
                                "source_penalty": 0.02,
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
        self.assertEqual(0.02, calibration["avg_source_penalty"])
        self.assertEqual({}, calibration["source_counts"])
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

    def test_summarizes_traditional_gf_diagnostics(self) -> None:
        summary = summarize_events(
            [
                {
                    "event": "track",
                    "fields": {
                        "traditional_gf_source": "global",
                        "traditional_gf_global": 0.2,
                        "traditional_gf_global_weight": 42.0,
                        "traditional_gf_segment_weight": 0.0,
                        "traditional_gf_blend": 0.0,
                        "traditional_gf_selected": 0.2,
                    },
                },
                {
                    "event": "track",
                    "fields": {
                        "traditional_gf_source": "blend",
                        "traditional_gf_global": 0.2,
                        "traditional_gf_global_weight": 50.0,
                        "traditional_gf_segment": -0.6,
                        "traditional_gf_segment_weight": 18.0,
                        "traditional_gf_blend": 0.5,
                        "traditional_gf_selected": -0.3,
                    },
                },
            ]
        )

        diagnostics = summary["traditional_gf_diagnostics"]  # type: ignore[assignment]
        self.assertEqual({"blend": 1, "global": 1}, diagnostics["source_counts"])  # type: ignore[index]
        averages = diagnostics["averages"]  # type: ignore[index]
        self.assertEqual(0.2, averages["global_guess_factor"])
        self.assertEqual(46.0, averages["global_weight"])
        self.assertEqual(-0.6, averages["segment_guess_factor"])
        self.assertEqual(9.0, averages["segment_weight"])
        self.assertEqual(0.25, averages["blend"])
        self.assertEqual(-0.05, averages["selected_guess_factor"])
        by_source = summary["traditional_gf_diagnostics_by_source"]  # type: ignore[assignment]
        self.assertEqual(1, by_source["global"]["count"])  # type: ignore[index]
        self.assertEqual(42.0, by_source["global"]["averages"]["global_weight"])  # type: ignore[index]
        self.assertEqual(1, by_source["blend"]["count"])  # type: ignore[index]
        self.assertEqual(18.0, by_source["blend"]["averages"]["segment_weight"])  # type: ignore[index]
        self.assertEqual(0.5, by_source["blend"]["averages"]["blend"])  # type: ignore[index]

    def test_profile_diagnostics_take_precedence_over_track_sampling(self) -> None:
        summary = summarize_events(
            [
                {
                    "event": "track",
                    "fields": {
                        "traditional_gf_source": "global",
                        "traditional_gf_global": 0.9,
                    },
                },
                {
                    "event": "gun.traditional_gf_profile",
                    "fields": {
                        "source": "segment",
                        "global_guess_factor": 0.2,
                    },
                },
            ]
        )

        diagnostics = summary["traditional_gf_diagnostics"]  # type: ignore[assignment]
        self.assertEqual({"segment": 1}, diagnostics["source_counts"])
        self.assertEqual(0.2, diagnostics["averages"]["global_guess_factor"])

    def test_summarizes_traditional_gf_profile_key_occupancy(self) -> None:
        summary = summarize_events(
            [
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "selected_gun": "traditional_gf",
                        "virtual_scores": {"traditional_gf": 0.2},
                        "traditional_gf_profile_key": [1, 2, 0],
                        "traditional_gf_source": "blend",
                        "traditional_gf_segment_weight": 18.0,
                        "traditional_gf_abs_error": 0.3,
                    },
                },
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "selected_gun": "traditional_gf",
                        "virtual_scores": {"traditional_gf": 0.3},
                        "traditional_gf_profile_key": [1, 2, 0],
                        "traditional_gf_source": "segment",
                        "traditional_gf_segment_weight": 36.0,
                        "traditional_gf_abs_error": 0.5,
                    },
                },
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "selected_gun": "traditional_gf",
                        "virtual_scores": {"traditional_gf": 0.1},
                        "traditional_gf_profile_key": [2, 1, 2],
                        "traditional_gf_source": "global",
                        "traditional_gf_segment_weight": 2.0,
                        "traditional_gf_abs_error": 0.7,
                    },
                },
            ]
        )

        profile_keys = summary["traditional_gf_profile_keys"]  # type: ignore[assignment]
        self.assertEqual(2, profile_keys["unique_keys"])
        cells = profile_keys["cells"]
        self.assertEqual(2, cells["1,2,0"]["visits"])
        self.assertEqual({"blend": 1, "segment": 1}, cells["1,2,0"]["source_counts"])
        self.assertEqual(27.0, cells["1,2,0"]["avg_segment_weight"])
        self.assertEqual(0.4, cells["1,2,0"]["avg_abs_error"])

    def test_summarizes_traditional_gf_real_hits_by_source(self) -> None:
        summary = summarize_events(
            [
                {
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 1, "aim_mode": "traditional_gf", "traditional_gf_source": "global"},
                },
                {"event": "bullet.hit_bot", "fields": {"bullet_id": 1}},
                {
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 2, "aim_mode": "traditional_gf", "traditional_gf_source": "segment"},
                },
            ]
        )

        by_source = summary["traditional_gf_source_real"]  # type: ignore[assignment]
        self.assertEqual({"global": 1, "segment": 1}, by_source["fired"])  # type: ignore[index]
        self.assertEqual({"global": 1}, by_source["hits"])  # type: ignore[index]
        self.assertEqual({"global": 1.0, "segment": 0.0}, by_source["hit_rate"])  # type: ignore[index]

    def test_traditional_gf_source_hits_do_not_cross_round_reset(self) -> None:
        summary = summarize_events(
            [
                {"event": "bullet.hit_bot", "fields": {"bullet_id": 9}},
                {"event": "round.reset", "fields": {"previous_turn": 80, "current_turn": 0}},
                {
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 9, "aim_mode": "traditional_gf", "traditional_gf_source": "global"},
                },
            ]
        )

        by_source = summary["traditional_gf_source_real"]  # type: ignore[assignment]
        self.assertEqual({"global": 1}, by_source["fired"])  # type: ignore[index]
        self.assertEqual({}, by_source["hits"])  # type: ignore[index]
        self.assertEqual({"global": 0.0}, by_source["hit_rate"])  # type: ignore[index]

    def test_traditional_gf_source_hits_resolve_hit_before_fired(self) -> None:
        summary = summarize_events(
            [
                {"event": "bullet.hit_bot", "fields": {"bullet_id": 9}},
                {
                    "event": "bullet.fired",
                    "fields": {"bullet_id": 9, "aim_mode": "traditional_gf", "traditional_gf_source": "blend"},
                },
            ]
        )

        by_source = summary["traditional_gf_source_real"]  # type: ignore[assignment]
        self.assertEqual({"blend": 1}, by_source["fired"])  # type: ignore[index]
        self.assertEqual({"blend": 1}, by_source["hits"])  # type: ignore[index]
        self.assertEqual({"blend": 1.0}, by_source["hit_rate"])  # type: ignore[index]

    def test_summarizes_traditional_gf_error(self) -> None:
        summary = summarize_events(
            [
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "selected_gun": "linear",
                        "guess_factor": 0.5,
                        "traditional_gf_guess_factor": 0.2,
                        "traditional_gf_error": 0.3,
                        "traditional_gf_abs_error": 0.3,
                        "traditional_gf_source": "global",
                    },
                },
                {
                    "event": "gun.wave_visit",
                    "fields": {
                        "selected_gun": "traditional_gf",
                        "guess_factor": -0.1,
                        "traditional_gf_guess_factor": 0.2,
                        "traditional_gf_error": -0.3,
                        "traditional_gf_abs_error": 0.3,
                        "traditional_gf_source": "blend",
                    },
                },
                {
                    "event": "gun.eval_wave_visit",
                    "fields": {
                        "selected_gun": "traditional_gf",
                        "guess_factor": 0.1,
                        "traditional_gf_guess_factor": 0.0,
                        "traditional_gf_error": 0.1,
                        "traditional_gf_abs_error": 0.1,
                        "traditional_gf_source": "segment",
                    },
                },
            ]
        )

        gf_error = summary["traditional_gf_error"]  # type: ignore[assignment]
        self.assertEqual(2, gf_error["production"]["count"])  # type: ignore[index]
        self.assertEqual(0.2, gf_error["production"]["avg_actual_guess_factor"])  # type: ignore[index]
        self.assertEqual(0.2, gf_error["production"]["avg_aim_guess_factor"])  # type: ignore[index]
        self.assertEqual(0.0, gf_error["production"]["avg_error"])  # type: ignore[index]
        self.assertEqual(0.3, gf_error["production"]["avg_abs_error"])  # type: ignore[index]
        self.assertEqual(1, gf_error["production_selected"]["count"])  # type: ignore[index]
        self.assertEqual(-0.3, gf_error["production_selected"]["avg_error"])  # type: ignore[index]
        self.assertEqual(1, gf_error["eval_selected"]["count"])  # type: ignore[index]
        self.assertEqual(0.1, gf_error["eval_selected"]["avg_abs_error"])  # type: ignore[index]
        by_source = summary["traditional_gf_error_by_source"]  # type: ignore[assignment]
        self.assertEqual(1, by_source["production"]["global"]["count"])  # type: ignore[index]
        self.assertEqual(0.3, by_source["production"]["global"]["avg_abs_error"])  # type: ignore[index]
        self.assertEqual(1, by_source["production_selected"]["blend"]["count"])  # type: ignore[index]
        self.assertEqual(-0.3, by_source["production_selected"]["blend"]["avg_error"])  # type: ignore[index]
        self.assertEqual(1, by_source["eval_selected"]["segment"]["count"])  # type: ignore[index]
        self.assertEqual(0.1, by_source["eval_selected"]["segment"]["avg_abs_error"])  # type: ignore[index]

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
            "wave_selected_avg": {},
            "wave_non_selected_avg": {},
            "eval_selected_avg": {},
            "eval_non_selected_avg": {},
            "wave_count": {},
            "eval_count": {},
            "traditional_gf_diagnostics": {},
            "traditional_gf_diagnostics_by_source": {},
            "traditional_gf_source_real": {},
            "traditional_gf_profile_keys": {},
            "traditional_gf_error": {},
            "traditional_gf_error_by_source": {},
            "calibration": {"2": {"linear": {"post_switch_hit_rate": 0.5}}},
        }

        with redirect_stdout(stream):
            _print_summary(summary)

        output = stream.getvalue()
        self.assertIn("wave_selected: {'linear': 2}", output)
        self.assertIn("eval_selected: {'dynamic_cluster': 3}", output)
        self.assertIn("wave_selected_avg:", output)
        self.assertIn("eval_non_selected_avg:", output)
        self.assertIn("traditional_gf_diagnostics:", output)
        self.assertIn("traditional_gf_diagnostics_by_source:", output)
        self.assertIn("traditional_gf_source_real:", output)
        self.assertIn("traditional_gf_error:", output)
        self.assertIn("traditional_gf_error_by_source:", output)
        self.assertIn("calibration:", output)


if __name__ == "__main__":
    unittest.main()
