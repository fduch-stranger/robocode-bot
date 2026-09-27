import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def load_turn_timing_summary_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "turn_timing_summary.py"
    spec = importlib.util.spec_from_file_location("turn_timing_summary", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["turn_timing_summary"] = module
    spec.loader.exec_module(module)
    return module


turn_timing_summary = load_turn_timing_summary_module()


def _timing(turn: int, decision_us: int, severity: str, **fields: object) -> dict[str, object]:
    return {
        "bot": "adaptive-prime",
        "event": "bot.turn_timing",
        "turn": turn,
        "fields": {"decision_elapsed_us": decision_us, "severity": severity, **fields},
    }


class TurnTimingSummaryTest(unittest.TestCase):
    def test_attributes_slow_turns_to_gc_or_top_phase(self) -> None:
        events = [
            _timing(25, 3000, "ok", phase_us={"aim": 2000, "movement": 800}),
            _timing(50, 3200, "ok", phase_us={"aim": 2200, "movement": 600}),
            _timing(61, 26000, "warn", gc_pause_us=21000, gc_max_generation=2, phase_us={"aim": 24000}),
            _timing(90, 18000, "warn", gc_pause_us=0, gc_max_generation=-1, phase_us={"aim": 3000, "movement": 14000}),
            {"bot": "adaptive-prime", "event": "bot.skipped_turn", "turn": 62, "fields": {"skipped_turn": 61}},
            _timing(25, 99999, "warn"),
        ]
        events[-1]["bot"] = "basic-gf-surfer-port"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "adaptive-prime-1.jsonl"
            path.write_text("".join(json.dumps(event) + "\n" for event in events) + "{partial", encoding="utf-8")

            summary = turn_timing_summary.summarize([Path(tmpdir)], "adaptive-prime")

        self.assertEqual(4, summary.timing_samples)
        self.assertEqual(2, summary.slow_turns)
        self.assertEqual(1, summary.skipped_turns)
        self.assertEqual(1, summary.slow_turns_gc_dominated)
        self.assertEqual({"gc": 1, "movement": 1}, summary.slow_turn_top_phase)
        self.assertEqual({"2": 1}, summary.slow_turn_gc_generations)
        self.assertEqual({"aim": 2100.0, "movement": 700.0}, summary.mean_phase_us_ok_turns)
        self.assertEqual(26000, summary.slowest[0]["decision_us"])
        self.assertEqual(26000, summary.decision_us["max"])


if __name__ == "__main__":
    unittest.main()
