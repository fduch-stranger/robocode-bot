import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def load_run_ab_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "run_ab.py"
    spec = importlib.util.spec_from_file_location("run_ab", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["run_ab"] = module
    spec.loader.exec_module(module)
    return module


run_ab = load_run_ab_module()


class RunAbTest(unittest.TestCase):
    def test_core_preset_contains_expected_matchups(self) -> None:
        preset = run_ab.PRESETS["adaptive-1v1-core"]

        self.assertEqual("Adaptive Prime", preset["targetBot"])
        self.assertEqual(
            ["adaptive-vs-chase", "adaptive-vs-circle", "adaptive-vs-sweep"],
            [matchup["name"] for matchup in preset["matchups"]],
        )

    def test_local_bot_presets_target_each_sparring_bot(self) -> None:
        expected = {
            "chase-1v1-core": ("Chase Lock", ["chase-vs-adaptive", "chase-vs-circle", "chase-vs-sweep"]),
            "circle-1v1-core": ("Circle Strafer", ["circle-vs-adaptive", "circle-vs-chase", "circle-vs-sweep"]),
            "sweep-1v1-core": ("Sweep Pressure", ["sweep-vs-adaptive", "sweep-vs-chase", "sweep-vs-circle"]),
        }

        for preset_name, (target_bot, matchup_names) in expected.items():
            with self.subTest(preset=preset_name):
                preset = run_ab.PRESETS[preset_name]
                self.assertEqual(target_bot, preset["targetBot"])
                self.assertEqual(matchup_names, [matchup["name"] for matchup in preset["matchups"]])

    def test_resolve_bot_args_keeps_legacy_token(self) -> None:
        repo = Path("/repo")

        args = run_ab.resolve_bot_args(repo, ["bots/adaptive-prime", "legacy:basic-gf-surfer"])

        self.assertEqual(["/repo/bots/adaptive-prime", "legacy:basic-gf-surfer"], args)

    def test_classify_delta_marks_regression_for_score_drop(self) -> None:
        self.assertEqual("regression", run_ab.classify_delta(1000, -30, 0, -1))
        self.assertEqual("regression", run_ab.classify_delta(1000, 10, -2, -1))
        self.assertEqual("win", run_ab.classify_delta(1000, 20, 0, -1))
        self.assertEqual("mixed", run_ab.classify_delta(1000, 0, 0, -1))

    def test_aggregate_results_writes_matchup_and_total_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            experiment_dir = Path(tmp)
            preset = {
                "matchups": [
                    {"name": "adaptive-vs-test", "bots": ["bots/adaptive-prime", "bots/test"]},
                ]
            }
            self._write_result(experiment_dir / "baseline/adaptive-vs-test/run-1/results.json", 1000, 10)
            self._write_result(experiment_dir / "candidate/adaptive-vs-test/run-1/results.json", 1040, 11)

            summary = run_ab.aggregate_results(experiment_dir, preset, repeats=1, target_bot="Adaptive Prime")

            self.assertEqual(40, summary["matchups"][0]["delta"]["totalScore"])
            self.assertEqual(1, summary["matchups"][0]["delta"]["firstPlaces"])
            self.assertEqual("win", summary["matchups"][0]["decision"])
            self.assertEqual(40, summary["totals"]["delta"]["totalScore"])
            self.assertEqual("win", summary["totals"]["decision"])

    def test_summary_markdown_contains_total_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "summary.md"
            summary = {
                "targetBot": "Adaptive Prime",
                "matchups": [
                    {
                        "name": "adaptive-vs-test",
                        "decision": "win",
                        "baseline": {"totalScore": 1000, "firstPlaces": 10},
                        "candidate": {"totalScore": 1040, "firstPlaces": 11},
                        "delta": {"totalScore": 40, "firstPlaces": 1},
                    }
                ],
                "totals": {
                    "decision": "win",
                    "baseline": {"totalScore": 1000, "firstPlaces": 10},
                    "candidate": {"totalScore": 1040, "firstPlaces": 11},
                    "delta": {"totalScore": 40, "firstPlaces": 1},
                },
            }

            run_ab.write_summary_markdown(summary, output)

            text = output.read_text()
            self.assertIn("| adaptive-vs-test | win | 1000 | 1040 | 40 | 10 | 11 | 1 |", text)
            self.assertIn("Decision: `win`", text)

    @staticmethod
    def _write_result(path: Path, score: int, first_places: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "createdAt": "2026-07-01T00:00:00Z",
            "gameType": "1v1",
            "rounds": 24,
            "botDirs": [],
            "results": [
                {
                    "rank": 1,
                    "name": "Adaptive Prime",
                    "version": "1.0",
                    "totalScore": score,
                    "survival": 100,
                    "bulletDamage": 200,
                    "ramDamage": 0,
                    "firstPlaces": first_places,
                },
                {
                    "rank": 2,
                    "name": "Opponent",
                    "version": "1.0",
                    "totalScore": 500,
                    "survival": 0,
                    "bulletDamage": 100,
                    "ramDamage": 0,
                    "firstPlaces": 0,
                },
            ],
        }
        path.write_text(json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
