import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def load_combat_economics_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "combat_economics_summary.py"
    spec = importlib.util.spec_from_file_location("combat_economics_summary", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["combat_economics_summary"] = module
    spec.loader.exec_module(module)
    return module


combat_economics = load_combat_economics_module()


def _event(name: str, turn: int, **fields: object) -> dict[str, object]:
    return {"bot": "adaptive-prime", "event": name, "turn": turn, "fields": fields}


class CombatEconomicsRoundTrackingTest(unittest.TestCase):
    def _round_accuracy(self, events: list[dict[str, object]], extra_lines: str = ""):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "adaptive-prime-1.jsonl"
            lines = "".join(json.dumps(event) + "\n" for event in events)
            path.write_text(lines + extra_lines, encoding="utf-8")
            return combat_economics._round_accuracy(Path(tmpdir), "adaptive-prime", None)

    def test_late_round_reset_after_turn_drop_does_not_open_phantom_round(self) -> None:
        rounds = self._round_accuracy(
            [
                _event("bullet.fired", 900, bullet_id=1, aim_mode="linear", power=2.0),
                _event("bot.skipped_turn", 1),
                _event("round.reset", 2),
                _event("bullet.fired", 30, bullet_id=2, aim_mode="linear", power=2.0),
            ]
        )

        self.assertEqual([1, 2], sorted(rounds))
        self.assertEqual(1, rounds[2]["shots"])

    def test_round_reset_without_turn_drop_still_opens_new_round(self) -> None:
        rounds = self._round_accuracy(
            [
                _event("bullet.fired", 900, bullet_id=1, aim_mode="linear", power=2.0),
                _event("round.reset", 1),
                _event("bullet.fired", 30, bullet_id=2, aim_mode="linear", power=2.0),
                _event("round.reset", 1),
                _event("bullet.fired", 40, bullet_id=3, aim_mode="linear", power=2.0),
            ]
        )

        self.assertEqual([1, 2, 3], sorted(rounds))

    def test_malformed_trailing_line_is_skipped(self) -> None:
        rounds = self._round_accuracy(
            [_event("bullet.fired", 10, bullet_id=1, aim_mode="linear", power=2.0)],
            extra_lines='{"bot": "adaptive-prime", "event": "bullet.fi',
        )

        self.assertEqual(1, rounds[1]["shots"])


if __name__ == "__main__":
    unittest.main()
