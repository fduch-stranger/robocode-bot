import unittest

from types import SimpleNamespace

from bot_core.target_snapshot import TargetSnapshot, target_from_hit_bot
from bot_core.targeting import TargetMemory, TargetSelector


class TargetingTest(unittest.TestCase):
    def test_hit_bot_snapshot_preserves_previous_motion(self) -> None:
        previous = TargetSnapshot(7, 60.0, 100.0, 100.0, 135.0, 6.0, 20)
        event = SimpleNamespace(victim_id=7, energy=55.0, x=120.0, y=130.0)

        target = target_from_hit_bot(event, 21, previous)  # type: ignore[arg-type]

        self.assertEqual(135.0, target.direction)
        self.assertEqual(6.0, target.speed)
        self.assertEqual(21, target.seen_turn)

    def test_target_memory_reports_stale_and_fresh_targets(self) -> None:
        memory = TargetMemory()
        fresh = TargetSnapshot(1, 80.0, 100.0, 120.0, 0.0, 0.0, 10)
        stale = TargetSnapshot(2, 60.0, 200.0, 220.0, 0.0, 0.0, 4)
        memory[fresh.bot_id] = fresh
        memory[stale.bot_id] = stale

        self.assertEqual([2], memory.stale_ids(turn_number=12, max_age=6))
        self.assertEqual([fresh], memory.fresh_targets(turn_number=12, max_age=3))

    def test_target_memory_returns_active_fire_threat_inside_window(self) -> None:
        memory = TargetMemory()
        target = TargetSnapshot(3, 50.0, 100.0, 100.0, 0.0, 0.0, 20)
        memory[target.bot_id] = target

        self.assertEqual(target, memory.active_fire_threat(3, threat_turn=20, turn_number=30, memory_turns=12))
        self.assertIsNone(memory.active_fire_threat(3, threat_turn=20, turn_number=40, memory_turns=12))
        self.assertIsNone(memory.active_fire_threat(None, threat_turn=20, turn_number=30, memory_turns=12))

    def test_target_selector_prefers_fresh_targets_when_available(self) -> None:
        memory = TargetMemory()
        stale_low_score = TargetSnapshot(1, 10.0, 100.0, 100.0, 0.0, 0.0, 1)
        fresh_high_score = TargetSnapshot(2, 90.0, 300.0, 300.0, 0.0, 0.0, 10)
        memory[stale_low_score.bot_id] = stale_low_score
        memory[fresh_high_score.bot_id] = fresh_high_score
        selector = TargetSelector(reacquire_turns=3)

        selection = selector.select(memory, current_target_id=1, turn_number=12, score=lambda target: target.energy)

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(fresh_high_score, selection.target)
        self.assertEqual(1, selection.fresh_candidates)
        self.assertTrue(selection.changed)

    def test_target_selector_falls_back_to_stale_targets(self) -> None:
        memory = TargetMemory()
        first = TargetSnapshot(1, 60.0, 100.0, 100.0, 0.0, 0.0, 1)
        second = TargetSnapshot(2, 30.0, 300.0, 300.0, 0.0, 0.0, 2)
        memory[first.bot_id] = first
        memory[second.bot_id] = second
        selector = TargetSelector(reacquire_turns=3)

        selection = selector.select(memory, current_target_id=2, turn_number=12, score=lambda target: target.energy)

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(second, selection.target)
        self.assertEqual(0, selection.fresh_candidates)
        self.assertFalse(selection.changed)


if __name__ == "__main__":
    unittest.main()
