import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def load_advisor_summary_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "advisor_summary.py"
    spec = importlib.util.spec_from_file_location("advisor_summary", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["advisor_summary"] = module
    spec.loader.exec_module(module)
    return module


advisor_summary = load_advisor_summary_module()


def _event(name: str, **fields: object) -> dict[str, object]:
    return {"bot": "adaptive-jev", "event": name, "fields": fields}


def _outcome(answer: str, realized: str, hit: bool) -> dict[str, object]:
    return _event("advisor.outcome", key="k", answer=answer, realized=realized, hit=hit, answered_before_visit=False)


class AdvisorSummaryTest(unittest.TestCase):
    def test_style_accuracy_errors_and_latency(self) -> None:
        events = [
            _event("advisor.request", kind="style", submit="queued"),
            _event("advisor.request", kind="surf", submit="rate_limited"),
            _event("advisor.answer", kind="style", choice="wave_surfer", rule="orbiter", latency_ms=250.0, latency_turns=80, model="jev-1.13.0", input_tokens=600),
            _event("advisor.answer", kind="style", choice="wave_surfer", rule="wave_surfer", latency_ms=300.0, latency_turns=90, model="jev-1.13.0", input_tokens=620),
            _event("advisor.error", kind="surf", error="timeout"),
            {"bot": "basic-gf-surfer-port", "event": "advisor.answer", "fields": {"kind": "style"}},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "adaptive-jev-1.jsonl"
            path.write_text("".join(json.dumps(event) + "\n" for event in events) + "{partial", encoding="utf-8")
            summary = advisor_summary.summarize([Path(tmpdir)], "adaptive-jev", truth="wave_surfer")

        self.assertEqual({"style": {"queued": 1}, "surf": {"rate_limited": 1}}, summary.requests)
        self.assertEqual({"style": 2}, summary.answers)
        self.assertEqual({"surf:timeout": 1}, summary.errors)
        self.assertEqual(["jev-1.13.0"], summary.models)
        self.assertEqual(610.0, summary.mean_input_tokens)
        self.assertEqual((1.0, 0.5, 0.5), (summary.style["jev_accuracy"], summary.style["rule_accuracy"], summary.style["jev_rule_agreement"]))

    def test_surf_information_test_detects_informative_disagreement(self) -> None:
        informative = [_outcome("reverse", "forward", True)] * 300 + [_outcome("reverse", "forward", False)] * 300
        informative += [_outcome("forward", "forward", True)] * 60 + [_outcome("forward", "forward", False)] * 540
        result = advisor_summary.surf_information_test([event["fields"] for event in informative])
        self.assertEqual(1200, result["answered_waves"])
        self.assertEqual((0.1, 0.5), (result["hit_rate_when_agree"], result["hit_rate_when_disagree"]))
        self.assertGreater(result["z"], 1.96)
        self.assertTrue(result["gate_passed"])

        uninformative = [_outcome("stop", "forward", index % 8 == 0) for index in range(600)]
        uninformative += [_outcome("forward", "forward", index % 8 == 0) for index in range(600)]
        result = advisor_summary.surf_information_test([event["fields"] for event in uninformative])
        self.assertLess(abs(result["z"]), 1.0)
        self.assertFalse(result["gate_passed"])


if __name__ == "__main__":
    unittest.main()
