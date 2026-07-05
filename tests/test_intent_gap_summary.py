import json
import tempfile
import unittest
from pathlib import Path

from tools import intent_gap_summary


def intent_line(bot: str, round_number: int, turn: int) -> str:
    return json.dumps({"botName": bot, "round": round_number, "turn": turn}) + "\n"


class IntentGapSummaryTest(unittest.TestCase):
    def test_summarize_records_reports_ok_for_consecutive_turns(self) -> None:
        records = [
            intent_gap_summary.IntentRecord("run/intents.jsonl", 1, "Adaptive Prime", 1, 1),
            intent_gap_summary.IntentRecord("run/intents.jsonl", 2, "Adaptive Prime", 1, 2),
            intent_gap_summary.IntentRecord("run/intents.jsonl", 3, "Adaptive Prime", 1, 3),
        ]

        summaries = intent_gap_summary.summarize_records(records)

        self.assertFalse(intent_gap_summary.has_gaps(summaries))
        self.assertEqual(1, len(summaries))
        self.assertEqual(0, summaries[0].missingTurns)
        self.assertEqual((), summaries[0].duplicateTurns)

    def test_summarize_records_detects_missing_ranges_and_duplicates(self) -> None:
        records = [
            intent_gap_summary.IntentRecord("run/intents.jsonl", 1, "Adaptive Prime", 1, 1),
            intent_gap_summary.IntentRecord("run/intents.jsonl", 2, "Adaptive Prime", 1, 2),
            intent_gap_summary.IntentRecord("run/intents.jsonl", 3, "Adaptive Prime", 1, 2),
            intent_gap_summary.IntentRecord("run/intents.jsonl", 4, "Adaptive Prime", 1, 5),
            intent_gap_summary.IntentRecord("run/intents.jsonl", 5, "Adaptive Prime", 1, 8),
        ]

        summary = intent_gap_summary.summarize_records(records)[0]

        self.assertTrue(intent_gap_summary.has_gaps([summary]))
        self.assertEqual(4, summary.missingTurns)
        self.assertEqual(("3-4", "6-7"), summary.missingRanges)
        self.assertEqual((2,), summary.duplicateTurns)
        self.assertEqual(2, summary.longestMissingRun)

    def test_cli_discovers_run_dir_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-001"
            run_dir.mkdir()
            intents_path = run_dir / "intents.jsonl"
            json_path = root / "summary.json"
            intents_path.write_text(
                "".join(
                    [
                        intent_line("Adaptive Prime", 1, 1),
                        intent_line("Adaptive Prime", 1, 3),
                        intent_line("Chase Lock", 1, 1),
                        intent_line("Chase Lock", 1, 2),
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = intent_gap_summary.main([str(root), "--json-output", str(json_path)])

            self.assertEqual(1, exit_code)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual("gap", payload["status"])
            by_bot = {round_summary["botName"]: round_summary for round_summary in payload["rounds"]}
            self.assertEqual(["2"], list(by_bot["Adaptive Prime"]["missingRanges"]))
            self.assertEqual([], list(by_bot["Chase Lock"]["missingRanges"]))


if __name__ == "__main__":
    unittest.main()
