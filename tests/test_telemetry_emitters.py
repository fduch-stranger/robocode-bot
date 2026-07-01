import unittest

from bot_core.energy import EnergyDropSignal, EnemyFirePowerPrediction, FireDecision, GunHeatState
from bot_core.gun import AimSolution, WaveVisit
from bot_core.movement import FlatteningDecision, GoToSurfDecision, MinimumRiskDecision, MovementCommand, MovementProfileVisit
from bot_core.radar import RadarCommand
from bot_core.target_snapshot import TargetSnapshot
from bot_core.telemetry.energy import (
    EnergyTelemetry,
    enemy_fire_detected_fields,
    energy_drop_ignored_fields,
    gun_heat_wave_fields,
)
from bot_core.telemetry.fire import (
    FireTelemetry,
    FireTick,
    SimpleTrackTick,
    bullet_fired_fields,
    bullet_hit_bot_fields,
    track_fields,
    wave_visit_fields,
)
from bot_core.telemetry.movement import (
    MovementTelemetry,
    duel_potential_fields,
    flattening_fields,
    goto_surf_fields,
    minimum_risk_fields,
    profile_visit_fields,
    wall_avoid_fields,
)
from bot_core.telemetry.targeting import (
    TargetingTelemetry,
    candidate_target_selection_fields,
    scan_new_fields,
    scan_reacquired_fields,
    target_drop_lost_fields,
    target_selection_fields,
)
from bot_core.targeting import TargetSelection


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, object]]] = []

    def log(self, event: str, **fields: object) -> None:
        self.records.append(("log", event, fields))

    def sample(self, event: str, **fields: object) -> None:
        self.records.append(("sample", event, fields))


class TelemetryEmitterTest(unittest.TestCase):
    def test_track_fields_preserve_adaptive_track_schema(self) -> None:
        target = TargetSnapshot(7, 81.0, 120.0, 160.0, 45.0, 4.0, 10)
        aim = AimSolution(
            predicted_x=130.04,
            predicted_y=170.05,
            gun_bearing=-2.345,
            mode="dynamic_cluster",
            guess_factor=0.4567,
            features=(0.0,) * 7,
            segment_key=(1, 2, 3),
            virtual_bearings={},
        )
        radar = RadarCommand(target, turn=4.444, mode="lock", bearing=-8.888, age=1)
        flattening = FlatteningDecision(1, True, "safer", 12, 2.5, 0.4)

        fields = track_fields(
            FireTick(
                target=target,
                age=2,
                distance=321.98,
                aim=aim,
                radar=radar,
                decision=FireDecision(False, "gun_alignment", 7),
                gun_samples=42,
                gun_scores={"linear": "0.42/9"},
                evade_direction=-1,
                evading=True,
                movement_mode="goto_surf",
                strafe_offset=91.55,
                flattening=flattening,
                last_enemy_fire_age=6,
                known_targets=3,
            )
        )

        self.assertEqual(
            {
                "target",
                "age",
                "distance",
                "gun_bearing",
                "radar_bearing",
                "radar_turn",
                "radar_mode",
                "radar_age",
                "predicted_x",
                "predicted_y",
                "aim_mode",
                "aim_guess_factor",
                "gun_samples",
                "gun_scores",
                "fire_alignment_limit",
                "hold_reason",
                "evade_direction",
                "evading",
                "movement_mode",
                "strafe_offset",
                "flatten_reason",
                "flatten_bucket",
                "last_enemy_fire_age",
                "known_targets",
            },
            set(fields),
        )
        self.assertEqual(-2.35, fields["gun_bearing"])
        self.assertEqual(0.457, fields["aim_guess_factor"])
        self.assertEqual("safer", fields["flatten_reason"])

    def test_energy_emitters_preserve_drop_and_fire_fields(self) -> None:
        ignored = EnergyDropSignal(False, "stale_scan", 1.2, 1.1, 0.1, None, None, 0)
        self.assertEqual(
            {
                "bot_id": 4,
                "reason": "stale_scan",
                "raw_drop": 1.2,
                "corrected_drop": 1.1,
                "correction": 0.1,
                "scan_gap": 5,
                "distance": 240.4,
                "previous_energy": 80.0,
                "energy": 78.8,
            },
            energy_drop_ignored_fields(4, ignored, 5, 240.44, 80.0, 78.8),
        )

        fire = EnergyDropSignal(True, "fire", 2.03, 1.93, 0.1, 1.93, 14, 20)
        prediction = EnemyFirePowerPrediction(1.5, 0.42, 12, "knn", mean_absolute_error=0.1234)
        fields = enemy_fire_detected_fields(
            4,
            fire,
            2,
            240.44,
            "active_duel",
            42,
            True,
            prediction,
            9,
            0.4567,
            previous_energy=80.0,
            energy=78.0,
            evade_direction=-1,
            known_targets=2,
            heat_state=GunHeatState(heat=1.386),
        )

        self.assertEqual(
            {
                "bot_id",
                "power",
                "raw_drop",
                "corrected_drop",
                "correction",
                "scan_gap",
                "distance",
                "bullet_travel_ticks",
                "previous_energy",
                "energy",
                "evasion",
                "evade_direction",
                "evade_until",
                "known_targets",
                "movement_wave",
                "gun_heat",
                "predicted_power",
                "prediction_error",
                "power_samples",
                "power_mae",
            },
            set(fields),
        )
        self.assertEqual(1.93, fields["power"])
        self.assertEqual(0.43, fields["prediction_error"])
        self.assertEqual(0.457, fields["power_mae"])

    def test_simple_bot_emitters_preserve_circle_sweep_fields(self) -> None:
        target = TargetSnapshot(7, 81.0, 120.0, 160.0, 45.0, 4.0, 10)
        aim = AimSolution(
            predicted_x=130.04,
            predicted_y=170.05,
            gun_bearing=-2.345,
            mode="linear",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(1, 2, 3),
            virtual_bearings={},
        )
        radar = RadarCommand(target, turn=4.444, mode="lock", bearing=-8.888, age=1)
        track = track_fields(
            SimpleTrackTick(target, 2, 321.98, aim, radar, 1.2, "gun_alignment", 42, {"linear": "0.42/9"}, 3)
        )
        self.assertEqual(
            {
                "target",
                "age",
                "distance",
                "gun_bearing",
                "radar_turn",
                "radar_mode",
                "radar_target",
                "radar_age",
                "firepower",
                "hold_reason",
                "predicted_x",
                "predicted_y",
                "aim_mode",
                "aim_guess_factor",
                "gun_samples",
                "gun_scores",
                "known_targets",
            },
            set(track),
        )
        self.assertIsNone(track["aim_guess_factor"])

        ignored = EnergyDropSignal(False, "not_fire", 0.4, 0.3, 0.1, None, None, 0)
        self.assertEqual(
            {"bot_id": 7, "reason": "not_fire", "raw_drop": 0.4, "corrected_drop": 0.3, "correction": 0.1, "scan_gap": 2, "distance": 200.1},
            energy_drop_ignored_fields(7, ignored, 2, 200.12),
        )

        fire = EnergyDropSignal(True, "fire", 1.51, 1.41, 0.1, 1.41, 13, 20)
        prediction = EnemyFirePowerPrediction(1.2, 0.75, 20, "knn", mean_absolute_error=0.2222)
        fire_fields = enemy_fire_detected_fields(
            7,
            fire,
            2,
            200.12,
            "active_duel",
            99,
            True,
            prediction,
            12,
            0.3333,
            evading=True,
            move_direction=-1,
        )
        self.assertEqual(
            {
                "bot_id",
                "power",
                "raw_drop",
                "corrected_drop",
                "correction",
                "scan_gap",
                "distance",
                "bullet_travel_ticks",
                "evasion",
                "evading",
                "move_direction",
                "evade_until",
                "movement_wave",
                "predicted_power",
                "prediction_confidence",
                "prediction_reason",
                "prediction_error",
                "power_samples",
                "power_mae",
            },
            set(fire_fields),
        )
        self.assertEqual(0.21, fire_fields["prediction_error"])

        flattening = FlatteningDecision(-1, True, "lower_danger", 4, 2.22, 1.11)
        self.assertEqual(
            {
                "target": 7,
                "suggested_direction": -1,
                "bucket": 4,
                "current_count": 2.2,
                "alternative_count": 1.1,
                "distance": 200.1,
            },
            flattening_fields(7, flattening, 200.12),
        )
        self.assertEqual({"x": 10.1, "y": 20.2, "center_bearing": -3.46, "move_direction": 1}, wall_avoid_fields(10.12, 20.23, -3.456, 1))

        self.assertEqual(
            {
                "previous": 3,
                "selected": 7,
                "score": 12.3,
                "candidate": 8,
                "candidate_score": 11.1,
                "previous_age": 4,
                "known_targets": 2,
            },
            candidate_target_selection_fields(3, target, 12.34, TargetSnapshot(8, 70, 1, 2, 0, 0, 10), 11.11, 4, 2),
        )

    def test_domain_emitters_record_concrete_events(self) -> None:
        sink = RecordingSink()
        target = TargetSnapshot(7, 81.0, 120.0, 160.0, 45.0, 4.0, 10)
        aim = AimSolution(
            predicted_x=130.04,
            predicted_y=170.05,
            gun_bearing=-2.345,
            mode="linear",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(1, 2, 3),
            virtual_bearings={},
        )
        radar = RadarCommand(target, turn=4.444, mode="lock", bearing=-8.888, age=1)
        fire_tick = SimpleTrackTick(target, 2, 321.98, aim, radar, 1.2, "gun_alignment", 42, {"linear": "0.42/9"}, 3)
        FireTelemetry(sink).sample_track(fire_tick)

        signal = EnergyDropSignal(True, "fire", 1.51, 1.41, 0.1, 1.41, 13, 20)
        prediction = EnemyFirePowerPrediction(1.2, 0.75, 20, "knn", mean_absolute_error=0.2222)
        EnergyTelemetry(sink).record_enemy_fire_detected(
            7,
            signal,
            2,
            200.12,
            "active_duel",
            99,
            True,
            prediction,
            12,
            0.3333,
            evading=True,
            move_direction=-1,
        )

        flattening = FlatteningDecision(-1, True, "lower_danger", 4, 2.22, 1.11)
        MovementTelemetry(sink).record_flattening(7, flattening, 200.12)
        TargetingTelemetry(sink).record_scan_new(7, 81.0, 120.0, 160.0)

        self.assertEqual(
            ["track", "enemy.fire_detected", "movement.flatten", "scan.new"],
            [event for _, event, _ in sink.records],
        )
        self.assertEqual("sample", sink.records[0][0])
        self.assertEqual(
            {
                "target",
                "age",
                "distance",
                "gun_bearing",
                "radar_turn",
                "radar_mode",
                "radar_target",
                "radar_age",
                "firepower",
                "hold_reason",
                "predicted_x",
                "predicted_y",
                "aim_mode",
                "aim_guess_factor",
                "gun_samples",
                "gun_scores",
                "known_targets",
            },
            set(sink.records[0][2]),
        )
        self.assertEqual(
            {
                "bot_id",
                "power",
                "raw_drop",
                "corrected_drop",
                "correction",
                "scan_gap",
                "distance",
                "bullet_travel_ticks",
                "evasion",
                "evading",
                "move_direction",
                "evade_until",
                "movement_wave",
                "predicted_power",
                "prediction_confidence",
                "prediction_reason",
                "prediction_error",
                "power_samples",
                "power_mae",
            },
            set(sink.records[1][2]),
        )
        self.assertEqual({"target", "suggested_direction", "bucket", "current_count", "alternative_count", "distance"}, set(sink.records[2][2]))
        self.assertEqual({"bot_id", "energy", "x", "y"}, set(sink.records[3][2]))

    def test_bullet_emitters_preserve_lifecycle_fields(self) -> None:
        tracked = {"aim_mode": "linear", "aim_guess_factor": 0.123}
        hit = bullet_hit_bot_fields(4, 99, 1.234, 5.678, 44.44, tracked)
        self.assertEqual(
            {
                "victim": 4,
                "bullet_id": 99,
                "power": 1.23,
                "damage": 5.68,
                "energy": 44.4,
                "aim_mode": "linear",
                "aim_guess_factor": 0.123,
            },
            hit,
        )

        fired = bullet_fired_fields(
            99,
            4,
            1.234,
            88.88,
            55.55,
            7,
            42,
            0.4567,
            12,
            tracked,
            target_age=None,
            target_x=None,
            target_y=120.04,
            shadow_bullets=3,
        )
        self.assertEqual(
            {
                "bullet_id",
                "target",
                "target_age",
                "target_x",
                "target_y",
                "power",
                "direction",
                "energy",
                "gun_waves",
                "shadow_bullets",
                "gun_samples",
                "gun_confidence",
                "gun_confidence_visits",
                "aim_mode",
                "aim_guess_factor",
            },
            set(fired),
        )
        self.assertIsNone(fired["target_age"])
        self.assertIsNone(fired["target_x"])
        self.assertEqual(120.0, fired["target_y"])

    def test_movement_emitters_preserve_adaptive_fields(self) -> None:
        command = MovementCommand("goto_surf", turn=-12.345, speed=8)
        surf = GoToSurfDecision(
            x=100.04,
            y=200.05,
            danger=0.1234,
            candidates=11,
            wave_kind="confirmed",
            hit_guess_factor=-0.4567,
            hit_bin=9,
            hit_turn=21,
            direction=-1,
            profile_danger=0.2,
            ensemble_danger=0.3,
            ensemble_samples=4.44,
            ensemble_weight=0.5555,
            wall_risk=0.01,
            distance_risk=0.02,
            travel_risk=0.03,
        )
        fields = goto_surf_fields(8, surf, command, evade_direction=1)
        self.assertEqual(
            {
                "target",
                "destination_x",
                "destination_y",
                "danger",
                "profile_danger",
                "ensemble_danger",
                "ensemble_samples",
                "ensemble_weight",
                "wall_risk",
                "distance_risk",
                "travel_risk",
                "candidates",
                "wave_kind",
                "hit_guess_factor",
                "hit_bin",
                "hit_turn",
                "evade_direction",
                "turn",
                "speed",
            },
            set(fields),
        )
        self.assertEqual(100.0, fields["destination_x"])
        self.assertEqual(-0.457, fields["hit_guess_factor"])
        self.assertEqual(4.4, fields["ensemble_samples"])

        risk = MinimumRiskDecision(10.04, 20.05, 0.9876, 14, 3, 123.45, reused=True, age=4)
        risk_fields = minimum_risk_fields(8, risk, command, 3, fire_threat_id=None, include_fire_threat=True)
        self.assertIn("fire_threat", risk_fields)
        self.assertIsNone(risk_fields["fire_threat"])

    def test_shared_emitters_cover_wave_profile_targeting_and_heat_wave(self) -> None:
        visit = WaveVisit(1, -0.2345, 17, 88.88, 199.99, "linear", {"linear": 0.5}, {"linear": "0.50/1"})
        self.assertEqual(-0.234, wave_visit_fields(visit)["guess_factor"])

        profile = MovementProfileVisit(2, 0.3456, 16, 1, 3.21, 9, 0.4567, 8.88)
        profile_fields = profile_visit_fields(profile)
        self.assertEqual(
            {"target", "guess_factor", "bin", "bucket", "visits", "wave_age", "ensemble_danger", "ensemble_samples"},
            set(profile_fields),
        )
        self.assertEqual(0.457, profile_fields["ensemble_danger"])

        flattening = FlatteningDecision(-1, True, "lower_danger", 4, 2.22, 1.11)
        self.assertEqual("lower_danger", flattening_fields(3, flattening, 250.09, current_direction=1, include_reason=True)["reason"])

        potential = duel_potential_fields(3, 10.04, 20.05, 0.1234, -0.4567, 300.09, "orbit", True, -1, MovementCommand("orbit", 1.234, 7))
        self.assertEqual(-0.457, potential["force_y"])

        prediction = EnemyFirePowerPrediction(1.7, 0.5, 8, "fallback", mean_absolute_error=None)
        heat = gun_heat_wave_fields(3, 1.66, prediction, 400.01, 1, True)
        self.assertEqual(
            {"bot_id", "power", "confidence", "samples", "reason", "power_mae", "distance", "target_age", "movement_wave"},
            set(heat),
        )
        self.assertIsNone(heat["power_mae"])
        self.assertEqual(1.66, heat["power"])

        target = TargetSnapshot(5, 60.0, 100.0, 120.0, 0.0, 0.0, 11)
        selection = TargetSelection(target, previous_id=4, fresh_candidates=2, score=33.33)
        self.assertEqual(33.3, target_selection_fields(selection, 3)["score"])
        self.assertEqual({"bot_id": 5, "energy": 60.1, "x": 100.1, "y": 120.1}, scan_new_fields(5, 60.12, 100.11, 120.11))
        self.assertEqual(
            {
                "bot_id": 5,
                "previous_age": 8,
                "previous_x": 100.0,
                "previous_y": 120.0,
                "x": 130.1,
                "y": 140.1,
            },
            scan_reacquired_fields(5, 8, target, 130.12, 140.12),
        )
        self.assertEqual(
            {"bot_id", "age", "cached_x", "cached_y", "cached_distance", "known_targets"},
            set(target_drop_lost_fields(target, 12, 300.04, 2)),
        )


if __name__ == "__main__":
    unittest.main()
