import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tools.ab_pool import compare, load_runs, main


def _write_run(root: Path, side: str, index: int, score: int, firsts: int, dealt: int, taken: int) -> None:
    run_dir = root / side / "adaptive-vs-basic-gf-surfer-port" / f"run-{index}"
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text(
        json.dumps(
            {
                "rounds": 24,
                "results": [
                    {"name": "Adaptive Prime", "totalScore": score, "firstPlaces": firsts, "bulletDamage": dealt},
                    {"name": "BasicGFSurfer Port", "totalScore": 1500, "firstPlaces": 24 - firsts, "bulletDamage": taken},
                ],
            }
        ),
        encoding="utf-8",
    )


class AbPoolTest(unittest.TestCase):
    def test_pools_baselines_across_experiments_and_reports_a_win(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            for index, score in enumerate((1600, 1650, 1550), start=1):
                _write_run(first, "baseline", index, score, 15, 600, 1350)
                _write_run(second, "baseline", index, score + 20, 15, 610, 1340)
            for index, score in enumerate((1900, 1950, 1850), start=1):
                _write_run(second, "candidate", index, score, 17, 750, 1150)

            candidate = load_runs([second], "candidate", "Adaptive Prime")
            baseline = load_runs([second, first], "baseline", "Adaptive Prime")
            summary = compare(candidate, baseline)

            self.assertEqual(3, len(candidate))
            self.assertEqual(6, len(baseline))
            metrics = summary["metrics"]
            self.assertAlmostEqual(1900.0, metrics["score"]["candidate_mean"])
            self.assertAlmostEqual(1610.0, metrics["score"]["baseline_mean"])
            self.assertAlmostEqual(1150.0, metrics["taken"]["candidate_mean"])
            self.assertGreater(metrics["score"]["z"], 2.0)
            self.assertEqual("win", summary["decision"])

    def test_side_directory_and_neutral_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "exp"
            for index, score in enumerate((1600, 1700, 1500, 1650), start=1):
                _write_run(root, "baseline", index, score, 15, 600, 1350)
            for index, score in enumerate((1620, 1720, 1520, 1670), start=1):
                _write_run(root, "candidate", index, score, 15, 605, 1345)

            side_dir = root / "candidate" / "adaptive-vs-basic-gf-surfer-port"
            candidate = load_runs([side_dir], "candidate", "Adaptive Prime")
            baseline = load_runs([root], "baseline", "Adaptive Prime")
            summary = compare(candidate, baseline)

            self.assertEqual(4, len(candidate))
            self.assertAlmostEqual(20.0, summary["metrics"]["score"]["delta"])
            self.assertEqual("neutral", summary["decision"])

    def test_cli_writes_json_and_fails_without_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "exp"
            for index in (1, 2):
                _write_run(root, "baseline", index, 1600, 15, 600, 1350)
                _write_run(root, "candidate", index, 1300, 12, 500, 1500)
            output = Path(temp_dir) / "summary.json"

            with redirect_stdout(StringIO()):
                exit_code = main(["--candidate", str(root), "--baseline", str(root), "--json-output", str(output)])
                missing = main(["--candidate", str(Path(temp_dir) / "none"), "--baseline", str(root)])

            self.assertEqual(0, exit_code)
            self.assertEqual(1, missing)
            summary = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(2, summary["candidate_runs"])
            self.assertIn(summary["decision"], {"negative", "neutral"})


if __name__ == "__main__":
    unittest.main()
