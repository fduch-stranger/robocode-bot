import unittest

from bot_core.energy import EnergyDropSignal, EnemyFirePowerPrediction, FireDecision, GunHeatState
from bot_core.gun import AimSolution, GunSwitchCandidate, TraditionalGfDiagnostics, WaveVisit
from bot_core.movement import FlatteningDecision, GoToSurfDecision, MinimumRiskDecision, MovementCommand, MovementProfileVisit
from bot_core.radar import RadarCommand
from bot_core.target_snapshot import TargetSnapshot
from bot_core.targeting import TargetSelection
from bot_core.telemetry.energy import EnergyTelemetry
from bot_core.telemetry.fire import FireTelemetry, FireTick, SimpleTrackTick
from bot_core.telemetry.movement import MovementTelemetry
from bot_core.telemetry.targeting import TargetingTelemetry


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, object]]] = []

    def log(self, event: str, **fields: object) -> None:
        self.records.append(("log", event, fields))

    def sample(self, event: str, **fields: object) -> None:
        self.records.append(("sample", event, fields))

    def only_record(self) -> tuple[str, str, dict[str, object]]:
        if len(self.records) != 1:
            raise AssertionError(f"expected one record, got {self.records!r}")
        return self.records[0]


class TelemetryEmitterTest(unittest.TestCase):
    @staticmethod
    def _target(target_id: int = 7) -> TargetSnapshot:
        return TargetSnapshot(target_id, 81.0, 120.0, 160.0, 45.0, 4.0, 10)

    @staticmethod
    def _aim(mode: str = "dynamic_cluster", guess_factor: float | None = 0.4567) -> AimSolution:
        return AimSolution(
            predicted_x=130.04,
            predicted_y=170.05,
            gun_bearing=-2.345,
            mode=mode,
            guess_factor=guess_factor,
            features=(0.0,) * 7,
            segment_key=(1, 2, 3),
            virtual_bearings={},
        )

    def test_fire_telemetry_records_adaptive_track_event(self) -> None:
        sink = RecordingSink()
        target = self._target()
        radar = RadarCommand(target, turn=4.444, mode="lock", bearing=-8.888, age=1)
        flattening = FlatteningDecision(1, True, "safer", 12, 2.5, 0.4)

        FireTelemetry(sink).sample_track(
            FireTick(
                target=target,
                age=2,
                distance=321.98,
                aim=self._aim(),
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

        kind, event, fields = sink.only_record()
        self.assertEqual(("sample", "track"), (kind, event))
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

    def test_fire_telemetry_records_simple_track_and_lifecycle_events(self) -> None:
        sink = RecordingSink()
        target = self._target()
        radar = RadarCommand(target, turn=4.444, mode="lock", bearing=-8.888, age=1)
        telemetry = FireTelemetry(sink)

        telemetry.sample_track(
            SimpleTrackTick(target, 2, 321.98, self._aim("linear", None), radar, 1.2, "gun_alignment", 42, {"linear": "0.42/9"}, 3)
        )
        telemetry.record_gun_switch_decision(
            4,
            AimSolution(
                130.04,
                170.05,
                -2.345,
                "linear",
                None,
                (0.0,) * 7,
                (1, 2, 3),
                {"linear": 0.0, "traditional_gf": 1.0},
                switch_candidates=(
                    GunSwitchCandidate("linear", True, 0.12, 0.12, 20, 55, 0.1, 0.045, "current"),
                    GunSwitchCandidate("traditional_gf", True, 0.18, 0.12, 40, 85, 0.1, 0.045, "visits"),
                ),
            ),
        )
        telemetry.record_wave_visit(
            WaveVisit(
                1,
                -0.2345,
                17,
                88.88,
                199.99,
                "linear",
                {"linear": 0.5},
                {"linear": "0.50/1"},
                traditional_gf_guess_factor=-0.1,
                traditional_gf_error=-0.1345,
                traditional_gf_abs_error=0.1345,
            )
        )
        telemetry.record_eval_wave_visit(
            WaveVisit(1, -0.1234, 3, 44.44, 188.88, "dynamic_cluster", {"dynamic_cluster": 0.6}, {"dynamic_cluster": "0.60/3"})
        )
        telemetry.record_bullet_hit_bot(4, 99, 1.234, 5.678, 44.44, {"aim_mode": "linear", "aim_guess_factor": 0.123})
        telemetry.record_bullet_fired(
            99,
            4,
            1.234,
            88.88,
            55.55,
            7,
            42,
            0.4567,
            12,
            {"aim_mode": "linear", "aim_guess_factor": 0.123},
            target_age=None,
            target_x=None,
            target_y=120.04,
            shadow_bullets=3,
            selected_gun_confidence=0.3456,
            selected_gun_confidence_visits=8,
        )
        telemetry.record_fire_drift(
            99,
            4,
            "linear",
            100.0,
            200.0,
            10.0,
            1.5,
            15.5,
            100.25,
            199.75,
            12.5,
            1.6,
            15.2,
        )

        self.assertEqual(
            [
                ("sample", "track"),
                ("log", "gun.switch_decision"),
                ("log", "gun.wave_visit"),
                ("log", "gun.eval_wave_visit"),
                ("log", "bullet.hit_bot"),
                ("log", "bullet.fired"),
                ("log", "gun.fire_drift"),
            ],
            [(kind, event) for kind, event, _ in sink.records],
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
            set(sink.records[0][2]),
        )
        self.assertIsNone(sink.records[0][2]["aim_guess_factor"])
        self.assertEqual("visits", sink.records[1][2]["candidates"][1]["reason"])
        self.assertEqual(0.18, sink.records[1][2]["candidates"][1]["raw_score"])
        self.assertEqual(0.0, sink.records[1][2]["candidates"][1]["confidence_penalty"])
        self.assertEqual(-0.234, sink.records[2][2]["guess_factor"])
        self.assertEqual(-0.1, sink.records[2][2]["traditional_gf_guess_factor"])
        self.assertEqual(-0.135, sink.records[2][2]["traditional_gf_error"])
        self.assertEqual(0.135, sink.records[2][2]["traditional_gf_abs_error"])
        self.assertEqual("dynamic_cluster", sink.records[3][2]["selected_gun"])
        self.assertEqual(5.68, sink.records[4][2]["damage"])
        self.assertIsNone(sink.records[5][2]["target_age"])
        self.assertIsNone(sink.records[5][2]["target_x"])
        self.assertEqual(120.0, sink.records[5][2]["target_y"])
        self.assertEqual(0.346, sink.records[5][2]["selected_gun_confidence"])
        self.assertEqual(8, sink.records[5][2]["selected_gun_confidence_visits"])
        self.assertEqual(2.5, sink.records[6][2]["direction_error"])
        self.assertEqual(0.354, sink.records[6][2]["source_error"])
        self.assertEqual(0.1, sink.records[6][2]["power_error"])
        self.assertEqual(-0.3, sink.records[6][2]["speed_error"])

    def test_fire_telemetry_records_traditional_gf_diagnostics(self) -> None:
        sink = RecordingSink()
        target = self._target()
        radar = RadarCommand(target, turn=4.444, mode="lock", bearing=-8.888, age=1)
        aim = AimSolution(
            130.04,
            170.05,
            -2.345,
            "traditional_gf",
            0.4,
            (0.0,) * 7,
            (1, 2, 3),
            {"traditional_gf": 1.0},
            traditional_gf=TraditionalGfDiagnostics(
                global_guess_factor=0.2,
                global_weight=42.4,
                segment_guess_factor=0.6,
                segment_weight=18.2,
                blend=0.35,
                selected_guess_factor=0.4,
                source="blend",
            ),
        )

        FireTelemetry(sink).sample_track(
            SimpleTrackTick(target, 2, 321.98, aim, radar, 1.2, "gun_alignment", 42, {"traditional_gf": "0.42/9"}, 3)
        )

        fields = sink.only_record()[2]
        self.assertEqual(0.2, fields["traditional_gf_global"])
        self.assertEqual(42.4, fields["traditional_gf_global_weight"])
        self.assertEqual(0.6, fields["traditional_gf_segment"])
        self.assertEqual(18.2, fields["traditional_gf_segment_weight"])
        self.assertEqual(0.35, fields["traditional_gf_blend"])
        self.assertEqual(0.4, fields["traditional_gf_selected"])
        self.assertEqual("blend", fields["traditional_gf_source"])

    def test_fire_telemetry_records_traditional_gf_profile_event(self) -> None:
        sink = RecordingSink()
        aim = AimSolution(
            130.04,
            170.05,
            -2.345,
            "traditional_gf",
            0.4,
            (0.0,) * 7,
            (1, 2, 3),
            {"traditional_gf": 1.0},
            traditional_gf=TraditionalGfDiagnostics(
                global_guess_factor=0.2,
                global_weight=42.4,
                segment_guess_factor=0.6,
                segment_weight=18.2,
                blend=0.35,
                selected_guess_factor=0.4,
                source="blend",
            ),
        )

        FireTelemetry(sink).record_traditional_gf_profile(4, aim)

        kind, event, fields = sink.only_record()
        self.assertEqual(("log", "gun.traditional_gf_profile"), (kind, event))
        self.assertEqual(4, fields["target"])
        self.assertEqual("traditional_gf", fields["aim_mode"])
        self.assertEqual(0.2, fields["global_guess_factor"])
        self.assertEqual(42.4, fields["global_weight"])
        self.assertEqual(0.6, fields["segment_guess_factor"])
        self.assertEqual(18.2, fields["segment_weight"])
        self.assertEqual(0.35, fields["blend"])
        self.assertEqual(0.4, fields["selected_guess_factor"])
        self.assertEqual("blend", fields["source"])

    def test_energy_telemetry_records_drop_fire_and_heat_wave_events(self) -> None:
        sink = RecordingSink()
        telemetry = EnergyTelemetry(sink)
        ignored = EnergyDropSignal(False, "stale_scan", 1.2, 1.1, 0.1, None, None, 0)
        fire = EnergyDropSignal(True, "fire", 2.03, 1.93, 0.1, 1.93, 14, 20)
        prediction = EnemyFirePowerPrediction(1.5, 0.42, 12, "knn", mean_absolute_error=0.1234)

        telemetry.record_drop_ignored(4, ignored, 5, 240.44, 80.0, 78.8)
        telemetry.record_enemy_fire_detected(
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
            inferred_fire_turn=15,
            fire_source_x=120.04,
            fire_source_y=180.05,
            fire_source_offset=12.345,
        )
        telemetry.record_gun_heat_wave(3, 1.66, EnemyFirePowerPrediction(1.7, 0.5, 8, "fallback", mean_absolute_error=None), 400.01, 1, True)

        self.assertEqual(["enemy.energy_drop_ignored", "enemy.fire_detected", "enemy.gun_heat_wave"], [event for _, event, _ in sink.records])
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
            sink.records[0][2],
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
                "inferred_fire_turn",
                "fire_source_x",
                "fire_source_y",
                "fire_source_offset",
            },
            set(sink.records[1][2]),
        )
        self.assertEqual(1.93, sink.records[1][2]["power"])
        self.assertEqual(0.43, sink.records[1][2]["prediction_error"])
        self.assertEqual(0.457, sink.records[1][2]["power_mae"])
        self.assertEqual(15, sink.records[1][2]["inferred_fire_turn"])
        self.assertEqual(120.0, sink.records[1][2]["fire_source_x"])
        self.assertEqual(180.1, sink.records[1][2]["fire_source_y"])
        self.assertEqual(12.35, sink.records[1][2]["fire_source_offset"])
        self.assertEqual(1.66, sink.records[2][2]["power"])
        self.assertIsNone(sink.records[2][2]["power_mae"])

    def test_movement_telemetry_records_simple_bot_events(self) -> None:
        sink = RecordingSink()
        telemetry = MovementTelemetry(sink)
        flattening = FlatteningDecision(-1, True, "lower_danger", 4, 2.22, 1.11)
        profile = MovementProfileVisit(2, 0.3456, 16, 1, 3.21, 9, 0.4567, 8.88)

        telemetry.sample_wall_avoid(x=10.12, y=20.23, center_bearing=-3.456, move_direction=1)
        telemetry.sample_target_wall_avoid(x=30.12, y=40.23, center_bearing=5.678, target_id=9)
        telemetry.sample_search_wall_avoid(x=50.12, y=60.23, center_bearing=-7.891, evade_direction=-1, near_wall=True)
        telemetry.sample_separation(
            target_id=4,
            distance=123.45,
            away_bearing=-12.345,
            target_speed=6,
            turn_limit=10,
            move_direction=-1,
            collision_escape=False,
        )
        telemetry.record_flattening(7, flattening, 200.12)
        telemetry.record_profile_visit(profile)

        self.assertEqual(
            [
                ("sample", "wall.avoid"),
                ("sample", "wall.avoid"),
                ("sample", "search.wall_avoid"),
                ("sample", "separate"),
                ("log", "movement.flatten"),
                ("log", "movement.profile_visit"),
            ],
            [(kind, event) for kind, event, _ in sink.records],
        )
        self.assertEqual({"x": 10.1, "y": 20.2, "center_bearing": -3.46, "move_direction": 1}, sink.records[0][2])
        self.assertEqual({"x": 30.1, "y": 40.2, "center_bearing": 5.68, "target": 9}, sink.records[1][2])
        self.assertEqual(
            {"x": 50.1, "y": 60.2, "center_bearing": -7.89, "evade_direction": -1, "near_wall": True},
            sink.records[2][2],
        )
        self.assertEqual(
            {
                "target": 4,
                "distance": 123.5,
                "away_bearing": -12.35,
                "target_speed": 6,
                "turn_limit": 10,
                "move_direction": -1,
                "collision_escape": False,
            },
            sink.records[3][2],
        )
        self.assertEqual(
            {
                "target": 7,
                "suggested_direction": -1,
                "bucket": 4,
                "current_count": 2.2,
                "alternative_count": 1.1,
                "distance": 200.1,
            },
            sink.records[4][2],
        )
        self.assertEqual(
            {"target", "guess_factor", "bin", "bucket", "visits", "wave_age", "ensemble_danger", "ensemble_samples"},
            set(sink.records[5][2]),
        )
        self.assertEqual(0.457, sink.records[5][2]["ensemble_danger"])

    def test_movement_telemetry_records_adaptive_events(self) -> None:
        sink = RecordingSink()
        telemetry = MovementTelemetry(sink)
        command = MovementCommand("goto_surf", turn=-12.345, speed=8)
        risk = MinimumRiskDecision(10.04, 20.05, 0.9876, 14, 3, 123.45, reused=True, age=4)
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
        flattening = FlatteningDecision(-1, True, "lower_danger", 4, 2.22, 1.11)

        telemetry.sample_minimum_risk(8, risk, command, 3, fire_threat_id=None, include_fire_threat=True)
        telemetry.sample_goto_surf(8, surf, command, evade_direction=1)
        telemetry.record_duel_flattening(3, flattening, 250.09, current_direction=1)
        telemetry.record_flattening_shadow(3, flattening, 250.09, current_direction=-1)
        telemetry.sample_duel_potential(3, 10.04, 20.05, 0.1234, -0.4567, 300.09, "orbit", True, -1, MovementCommand("orbit", 1.234, 7))

        self.assertEqual(
            ["movement.minimum_risk", "movement.goto_surf", "movement.duel_flatten", "movement.flatten_shadow", "movement.duel_potential"],
            [event for _, event, _ in sink.records],
        )
        self.assertIsNone(sink.records[0][2]["fire_threat"])
        self.assertEqual(100.0, sink.records[1][2]["destination_x"])
        self.assertEqual(-0.457, sink.records[1][2]["hit_guess_factor"])
        self.assertEqual(4.4, sink.records[1][2]["ensemble_samples"])
        self.assertEqual("lower_danger", sink.records[2][2]["reason"])
        self.assertNotIn("reason", sink.records[3][2])
        self.assertEqual(-0.457, sink.records[4][2]["force_y"])

    def test_targeting_telemetry_records_targeting_events(self) -> None:
        sink = RecordingSink()
        telemetry = TargetingTelemetry(sink)
        target = TargetSnapshot(5, 60.0, 100.0, 120.0, 0.0, 0.0, 11)
        candidate = TargetSnapshot(8, 70.0, 1.0, 2.0, 0.0, 0.0, 10)
        selection = TargetSelection(target, previous_id=4, fresh_candidates=2, score=33.33)

        telemetry.sample_search(known_targets=0)
        telemetry.sample_reacquire(
            target=target,
            age=6,
            distance=200.04,
            radar_bearing=-3.456,
            radar_direction=180.123,
            radar_turn=11.111,
            radar_mode="reacquire",
            radar_sweep=-1,
            x=90.04,
            y=110.05,
            known_targets=2,
        )
        telemetry.record_scan_new(5, 60.12, 100.11, 120.11)
        telemetry.record_scan_reacquired(5, 8, target, 130.12, 140.12)
        telemetry.record_target_selection(selection, 3)
        telemetry.record_candidate_selection(3, target, 12.34, candidate, 11.11, 4, 2)
        telemetry.record_target_drop_lost(target, 12, 300.04, 2)

        self.assertEqual(
            ["search", "target.reacquire", "scan.new", "scan.reacquired", "target.select", "target.select", "target.drop_lost"],
            [event for _, event, _ in sink.records],
        )
        self.assertEqual({"known_targets": 0}, sink.records[0][2])
        self.assertEqual(
            {
                "target": 5,
                "age": 6,
                "distance": 200.0,
                "radar_bearing": -3.46,
                "radar_direction": 180.12,
                "radar_turn": 11.11,
                "radar_mode": "reacquire",
                "radar_sweep": -1,
                "x": 90.0,
                "y": 110.0,
                "known_targets": 2,
            },
            sink.records[1][2],
        )
        self.assertEqual({"bot_id": 5, "energy": 60.1, "x": 100.1, "y": 120.1}, sink.records[2][2])
        self.assertEqual(
            {
                "bot_id": 5,
                "previous_age": 8,
                "previous_x": 100.0,
                "previous_y": 120.0,
                "x": 130.1,
                "y": 140.1,
            },
            sink.records[3][2],
        )
        self.assertEqual(33.3, sink.records[4][2]["score"])
        self.assertEqual(
            {
                "previous": 3,
                "selected": 5,
                "score": 12.3,
                "candidate": 8,
                "candidate_score": 11.1,
                "previous_age": 4,
                "known_targets": 2,
            },
            sink.records[5][2],
        )
        self.assertEqual(
            {"bot_id", "age", "cached_x", "cached_y", "cached_distance", "known_targets"},
            set(sink.records[6][2]),
        )


if __name__ == "__main__":
    unittest.main()
