import unittest

from bot_core.combat import CombatProfileConfig, CombatProfileStore, inferred_fire_confidence


class CombatProfileStoreTest(unittest.TestCase):
    def test_counts_accepted_shots_even_without_target_attribution(self) -> None:
        store = CombatProfileStore()

        self.assertTrue(store.record_own_fire(9, None, 1, 0.7, gun_mode=None))
        self.assertTrue(store.record_own_fire(10, 7, 2, 1.5, gun_mode="linear"))
        self.assertFalse(store.record_own_fire(10, 7, 2, 1.5, gun_mode="linear"))
        self.assertIsNone(store.resolve_own_bullet(12, 99, "hit_bot", damage=7.0))
        resolution = store.resolve_own_bullet(18, 2, "hit_bot", damage=7.0)
        unattributed = store.resolve_own_bullet(19, 1, "hit_wall")

        self.assertIsNotNone(resolution)
        self.assertIsNotNone(unattributed)
        assert resolution is not None
        self.assertEqual("linear", resolution.gun_mode)
        self.assertEqual("hit_bot", resolution.outcome)
        totals = store.snapshot(7, 18).lifetime
        self.assertEqual(1, totals.own_accepted_shots)
        self.assertEqual(1, totals.own_resolved_shots)
        self.assertEqual(1, totals.own_hits)
        self.assertEqual(0, totals.own_misses)
        self.assertAlmostEqual(1.5, totals.own_fired_energy)
        self.assertAlmostEqual(7.0, totals.own_hit_damage)
        unattributed_totals = store.snapshot(None, 19).lifetime
        self.assertEqual(1, unattributed_totals.own_accepted_shots)
        self.assertEqual(1, unattributed_totals.own_misses)
        self.assertAlmostEqual(0.7, unattributed_totals.own_fired_energy)

    def test_resolves_wall_bullet_and_round_end_as_misses(self) -> None:
        store = CombatProfileStore()
        for bullet_id in range(3):
            store.record_own_fire(10 + bullet_id, 7, bullet_id, 1.0)

        store.resolve_own_bullet(20, 0, "hit_wall")
        store.resolve_own_bullet(21, 1, "hit_bullet")
        round_end = store.close_round(50)

        self.assertEqual(1, len(round_end))
        self.assertEqual("round_end", round_end[0].outcome)
        totals = store.snapshot(7, 50).lifetime
        self.assertEqual(3, totals.own_accepted_shots)
        self.assertEqual(3, totals.own_resolved_shots)
        self.assertEqual(3, totals.own_misses)
        self.assertEqual(0, store.pending_own_bullets)

    def test_late_hit_corrects_same_turn_provisional_miss(self) -> None:
        store = CombatProfileStore()
        store.record_own_fire(10, 7, 1, 0.7, gun_mode="dynamic_cluster")
        provisional = store.resolve_own_bullet(20, 1, "round_end")

        corrected = store.resolve_own_bullet(20, 1, "hit_bot", damage=2.8)

        assert provisional is not None
        assert corrected is not None
        self.assertEqual("round_end", corrected.previous_outcome)
        self.assertEqual("hit_bot", corrected.outcome)
        totals = store.snapshot(7, 20).lifetime
        self.assertEqual(1, totals.own_accepted_shots)
        self.assertEqual(1, totals.own_resolved_shots)
        self.assertEqual(1, totals.own_hits)
        self.assertEqual(0, totals.own_misses)
        self.assertAlmostEqual(2.8, totals.own_hit_damage)

    def test_late_hit_does_not_rewrite_a_durable_miss(self) -> None:
        store = CombatProfileStore()
        store.record_own_fire(10, 7, 1, 0.7, gun_mode="dynamic_cluster")

        durable = store.resolve_own_bullet(20, 1, "hit_wall")
        corrected = store.resolve_own_bullet(20, 1, "hit_bot", damage=2.8)

        self.assertIsNotNone(durable)
        self.assertIsNone(corrected)
        totals = store.snapshot(7, 20).lifetime
        self.assertEqual(0, totals.own_hits)
        self.assertEqual(1, totals.own_misses)
        self.assertAlmostEqual(0.0, totals.own_hit_damage)

    def test_late_terminal_turn_fire_is_closed_by_repeated_close(self) -> None:
        store = CombatProfileStore()

        self.assertEqual((), store.close_round(20))
        self.assertEqual(20, store.round_closed_turn)
        self.assertTrue(store.record_own_fire(20, 7, 1, 0.7, gun_mode="dynamic_cluster"))

        resolutions = store.close_round(20)

        self.assertEqual(1, len(resolutions))
        self.assertEqual("round_end", resolutions[0].outcome)
        totals = store.snapshot(7, 20).lifetime
        self.assertEqual(1, totals.own_accepted_shots)
        self.assertEqual(1, totals.own_resolved_shots)
        self.assertEqual(0, store.pending_own_bullets)

        store.clear_round_state()
        self.assertIsNone(store.round_closed_turn)

    def test_recent_metrics_share_one_turn_window(self) -> None:
        store = CombatProfileStore(CombatProfileConfig(recent_turns=20))
        store.record_own_fire(10, 7, 1, 1.0)
        store.resolve_own_bullet(15, 1, "hit_bot", damage=4.0)
        store.record_enemy_fire(18, 7, 1.9, 1.0)
        store.record_enemy_hit(19, 7, 1.9, 9.4, matched_wave=True)

        snapshot = store.snapshot(7, 35)

        self.assertEqual(16, snapshot.recent_window_start)
        self.assertEqual(0, snapshot.recent.own_accepted_shots)
        self.assertEqual(0, snapshot.recent.own_hits)
        self.assertEqual(1, snapshot.recent.enemy_inferred_shots)
        self.assertEqual(1, snapshot.recent.enemy_hits)
        self.assertEqual(1, snapshot.lifetime.own_accepted_shots)
        self.assertEqual(1, snapshot.lifetime.own_hits)

    def test_confidence_weights_enemy_fire_without_changing_raw_count(self) -> None:
        store = CombatProfileStore()
        store.record_enemy_fire(10, 7, 1.0, 1.0)
        store.record_enemy_fire(20, 7, 2.0, 0.5)

        totals = store.snapshot(7, 20).lifetime

        self.assertEqual(2, totals.enemy_inferred_shots)
        self.assertAlmostEqual(1.5, totals.enemy_weighted_shots)
        self.assertAlmostEqual(3.0, totals.enemy_inferred_fired_energy)
        self.assertAlmostEqual(2.0, totals.enemy_weighted_fired_energy)
        self.assertAlmostEqual(0.75, totals.enemy_average_fire_confidence)

    def test_enemy_hit_match_coverage_and_observable_tags(self) -> None:
        store = CombatProfileStore(
            CombatProfileConfig(
                recent_turns=100,
                min_conversion_resolutions=2,
                min_enemy_fire_samples=2,
            )
        )
        for bullet_id in range(2):
            store.record_own_fire(10 + bullet_id, 7, bullet_id, 1.0)
            store.resolve_own_bullet(20 + bullet_id, bullet_id, "hit_wall")
        store.record_enemy_fire(22, 7, 1.9, 0.5)
        store.record_enemy_fire(23, 7, 1.9, 0.5)
        store.record_enemy_hit(24, 7, 1.9, 20.0, matched_wave=True)
        store.record_enemy_hit(25, 7, 1.9, 20.0, matched_wave=False)

        snapshot = store.snapshot(7, 25)

        self.assertAlmostEqual(0.5, snapshot.recent.enemy_hit_match_coverage)
        self.assertEqual(
            (
                "damage_deficit",
                "low_our_conversion",
                "high_enemy_damage",
                "enemy_fire_detection_weak",
            ),
            snapshot.tags,
        )

    def test_round_clear_keeps_lifetime_and_drops_recent_state(self) -> None:
        store = CombatProfileStore()
        store.record_enemy_fire(10, 7, 1.9, 1.0)

        store.clear_round_state()

        snapshot = store.snapshot(7, 1)
        self.assertEqual(0, snapshot.recent.enemy_inferred_shots)
        self.assertEqual(1, snapshot.lifetime.enemy_inferred_shots)

    def test_inferred_fire_confidence_decays_with_scan_gap(self) -> None:
        self.assertEqual(1.0, inferred_fire_confidence(1))
        self.assertAlmostEqual(0.85, inferred_fire_confidence(2))
        self.assertAlmostEqual(0.7, inferred_fire_confidence(3))
        self.assertEqual(0.55, inferred_fire_confidence(4))
        self.assertEqual(0.55, inferred_fire_confidence(20))


if __name__ == "__main__":
    unittest.main()
