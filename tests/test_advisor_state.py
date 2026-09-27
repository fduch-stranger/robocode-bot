import math
import unittest

from bot_core.advisors.observers import EnemyStyleObserver, SurfObserver, SurfRecord, outcome_option, wave_surf_features
from bot_core.advisors.schemas import STYLE_OPTIONS, SURF_OPTIONS, parse_choice, style_questions, surf_questions
from bot_core.advisors.state_summary import (
    StyleFeatures,
    SurfFeatures,
    bucket,
    hit_region,
    rule_based_style,
    style_state,
    surf_state,
)

PROTOTYPES = {
    "wave_surfer": StyleFeatures(900, 7.2, 6.4, 6.0, 2.6, 420.0, 45.0, 0.0, 2.0, 0.0, 0.15, 0.04),
    "orbiter": StyleFeatures(900, 8.0, 7.4, 1.0, 1.0, 380.0, 30.0, 0.0, 1.6, 0.0, 0.1, 0.25),
    "chaser": StyleFeatures(900, 7.5, 3.0, 2.5, 1.1, 180.0, 60.0, -40.0, 2.5, 2.0, 0.1, 0.18),
    "sweeper": StyleFeatures(900, 7.8, 4.0, 3.0, 1.0, 380.0, 150.0, 0.0, 4.0, 0.2, 0.2, 0.1),
    "oscillator": StyleFeatures(900, 5.0, 4.5, 14.0, 1.0, 400.0, 25.0, 0.0, 0.3, 0.0, 0.1, 0.06),
    "linear_mover": StyleFeatures(900, 8.0, 5.0, 0.8, 1.0, 400.0, 120.0, 0.0, 0.2, 0.0, 0.4, 0.3),
    "random_mover": StyleFeatures(900, 5.5, 3.5, 8.0, 1.0, 380.0, 80.0, 0.0, 6.5, 0.1, 0.2, 0.08),
    "stationary": StyleFeatures(900, 0.1, 0.05, 0.0, None, 400.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.9),
}


class AdvisorStateSummaryTest(unittest.TestCase):
    def test_bucket_uses_first_limit_above_the_value(self) -> None:
        edges = ((1.0, "low"), (2.0, "mid"))
        self.assertEqual(["low", "mid", "high"], [bucket(value, edges, "high") for value in (0.5, 1.0, 2.5)])

    def test_rule_based_style_classifies_every_prototype(self) -> None:
        for label, features in PROTOTYPES.items():
            with self.subTest(label=label):
                self.assertEqual(label, rule_based_style(features))

    def test_style_state_holds_only_named_buckets(self) -> None:
        state = style_state(PROTOTYPES["wave_surfer"])
        values = list(state["enemy"].values()) + [state["observed_for"]]
        self.assertTrue(all(isinstance(value, str) for value in values))
        self.assertEqual("strongly tied to our shots", state["enemy"]["direction_changes_vs_our_shots"])
        self.assertEqual("unknown", style_state(PROTOTYPES["stationary"])["enemy"]["direction_changes_vs_our_shots"])

    def test_surf_state_aggregates_hit_regions_in_code(self) -> None:
        features = SurfFeatures(420.0, 1.9, 30.0, 8.0, 0.95, 0.3, 1.0, (0.7, 0.6, 0.0, -0.8))
        state = surf_state(features)
        self.assertEqual("most", state["recent_hits_on_us"]["far ahead"])
        self.assertEqual("some", state["recent_hits_on_us"]["where we were"])
        self.assertEqual("none", state["recent_hits_on_us"]["slightly behind"])
        self.assertEqual("a wall is close", state["us"]["room_ahead"])
        self.assertEqual("no hits yet", surf_state(SurfFeatures(420.0, 1.9, 30.0, 8.0, 0.95, 1.0, 1.0, ()))["recent_hits_on_us"])
        self.assertEqual(["far ahead", "where we were", "far behind"], [hit_region(gf) for gf in (0.8, 0.1, -0.9)])

    def test_questions_and_answer_parsing(self) -> None:
        self.assertEqual(set(STYLE_OPTIONS), set(style_questions()["enemy_style"]["criteria"]))
        self.assertEqual({"forward", "reverse", "stop"}, set(surf_questions()["surf_side"]["criteria"]))
        answer = parse_choice(
            {"type": "choice", "choice": "stop", "probabilities": {"stop": 0.7, "forward": 0.3, "bogus": 1}, "confidence": 0.6},
            SURF_OPTIONS,
        )
        self.assertEqual(("stop", 0.6, {"stop": 0.7, "forward": 0.3}), (answer.choice, answer.confidence, answer.probabilities))
        self.assertIsNone(parse_choice({"type": "choice", "choice": "left"}, SURF_OPTIONS))
        self.assertIsNone(parse_choice({"type": "noul", "noul": 0.9}, SURF_OPTIONS))


class AdvisorObserversTest(unittest.TestCase):
    def test_orbiting_enemy_reads_as_sideways_and_steady(self) -> None:
        observer = EnemyStyleObserver()
        for turn in range(1, 301):
            angle = turn * 8.0 / 300.0
            x, y = 400.0 + 300.0 * math.cos(angle), 300.0 + 300.0 * math.sin(angle)
            heading = math.degrees(angle) + 90.0
            observer.observe_scan(1, turn, 400.0, 300.0, x, y, heading, 8.0, 800.0, 600.0)
        features = observer.features()
        self.assertEqual(300, features.observed_turns)
        self.assertGreater(features.lateral_share, 0.95)
        self.assertLess(features.distance_spread, 1.0)
        self.assertEqual(0.0, features.reversals_per_100_turns)
        self.assertEqual("orbiter", rule_based_style(features))

    def test_reversals_timed_to_our_wave_passes_raise_the_lift(self) -> None:
        observer = EnemyStyleObserver()
        direction = 1
        for turn in range(1, 401):
            if turn % 20 == 1:
                observer.observe_our_shot(1, turn, 300.0, 15.0)  # passes the enemy 20 turns later
            if turn > 20 and turn % 20 == 1:
                direction *= -1
            observer.observe_scan(1, turn, 400.0, 300.0, 400.0, 600.0, 0.0, 8.0 * direction, 800.0, 600.0)
        features = observer.features()
        self.assertGreater(features.reversals_per_100_turns, 4.0)
        self.assertIsNotNone(features.reversal_shot_lift)
        self.assertGreater(features.reversal_shot_lift, 2.0)

    def test_surf_features_measure_room_and_power(self) -> None:
        features = wave_surf_features(100.0, 300.0, 90.0, 8.0, 500.0, 300.0, 14.0, 10.0, 40.0, (0.5,))
        self.assertAlmostEqual(2.0, features.bullet_power)
        self.assertAlmostEqual(400.0 / 14.0, features.flight_turns)
        self.assertAlmostEqual(1.0, features.own_lateral_share)
        self.assertLess(features.room_forward, 0.4)
        self.assertEqual(1.0, features.room_reverse)

    def test_surf_outcome_needs_both_answer_and_visit_in_any_order(self) -> None:
        observer = SurfObserver()
        observer.track(SurfRecord("a", 10))
        observer.track(SurfRecord("b", 12))
        self.assertIsNone(observer.record_answer("a", "reverse", 0.8, 40))
        done = observer.record_visit("a", 35, 0.6, True)
        self.assertEqual(("reverse", 35, True), (done.answer, done.visit_turn, done.hit))
        self.assertIsNone(observer.record_visit("b", 36, -0.1, False))
        done = observer.record_answer("b", "stop", 0.5, 50)
        self.assertEqual(("stop", 36, False), (done.answer, done.visit_turn, done.hit))
        self.assertEqual((0.6,), observer.recent_hit_guess_factors)
        self.assertEqual(["forward", "stop", "reverse"], [outcome_option(gf) for gf in (0.5, 0.1, -0.4)])


if __name__ == "__main__":
    unittest.main()
