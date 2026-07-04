import json
import tempfile
import unittest
from pathlib import Path

from tools.surfer_glitch_analysis import analyze_experiment, analyze_run, discover_run_dirs


class SurferGlitchAnalysisTest(unittest.TestCase):
    def test_filters_high_accuracy_rounds_from_cumulative_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "baseline" / "run-01"
            _write_run(
                run_dir,
                [
                    {"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1},
                    {"round": 2, "score": 180, "survival": 50, "bulletDamage": 120, "ramDamage": 0, "firstPlaces": 1},
                ],
                [
                    [_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(8)],
                    [_fired(2, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(2)],
                ],
            )

            summary = analyze_run(run_dir)

        self.assertEqual("baseline", summary.side)
        self.assertEqual(2, summary.raw.rounds)
        self.assertEqual(180, summary.raw.score)
        self.assertEqual(1, summary.raw.firstPlaces)
        self.assertEqual(10, summary.raw.hits)
        self.assertEqual(1, summary.filtered.rounds)
        self.assertEqual(80, summary.filtered.score)
        self.assertEqual(0, summary.filtered.firstPlaces)
        self.assertEqual(2, summary.filtered.hits)
        self.assertEqual(1, summary.filtered.excludedRounds)
        self.assertTrue(summary.rounds[0].excludedGlitch)
        self.assertFalse(summary.rounds[1].excludedGlitch)

    def test_aggregates_baseline_candidate_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root / "baseline" / "run-01",
                [
                    {"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1},
                    {"round": 2, "score": 180, "survival": 50, "bulletDamage": 120, "ramDamage": 0, "firstPlaces": 1},
                ],
                [
                    [_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(8)],
                    [_fired(2, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(2)],
                ],
            )
            _write_run(
                root / "candidate" / "run-01",
                [
                    {"round": 1, "score": 90, "survival": 50, "bulletDamage": 30, "ramDamage": 0, "firstPlaces": 1},
                    {"round": 2, "score": 210, "survival": 100, "bulletDamage": 110, "ramDamage": 0, "firstPlaces": 2},
                ],
                [
                    [_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(1)],
                    [_fired(2, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(3)],
                ],
            )

            summary = analyze_experiment([root])

        self.assertEqual(2, summary["runCount"])
        self.assertEqual(80, summary["filtered"]["baseline"]["score"])
        self.assertEqual(210, summary["filtered"]["candidate"]["score"])
        self.assertEqual(130, summary["filtered"]["delta"]["score"])
        self.assertAlmostEqual(80.0, summary["filtered"]["baseline"]["scorePerRound"])
        self.assertAlmostEqual(105.0, summary["filtered"]["candidate"]["scorePerRound"])
        self.assertAlmostEqual(25.0, summary["filtered"]["delta"]["scorePerRound"])
        self.assertEqual(2, summary["filtered"]["delta"]["firstPlaces"])
        self.assertEqual(-1, summary["filtered"]["delta"]["excludedRounds"])
        self.assertEqual(4, summary["filtered"]["candidate"]["dynamicHits"])
        self.assertEqual(80, summary["pairedFiltered"]["baseline"]["score"])
        self.assertEqual(120, summary["pairedFiltered"]["candidate"]["score"])
        self.assertEqual(40, summary["pairedFiltered"]["delta"]["score"])
        self.assertAlmostEqual(40.0, summary["pairedFiltered"]["delta"]["scorePerRound"])
        self.assertEqual([2], summary["pairedFiltered"]["pairs"][0]["validRounds"])
        self.assertEqual([1], summary["pairedFiltered"]["pairs"][0]["baselineExcludedRounds"])
        self.assertEqual([], summary["pairedFiltered"]["pairs"][0]["candidateExcludedRounds"])
        round_comparison = summary["pairedFiltered"]["pairs"][0]["rounds"][0]
        self.assertEqual(2, round_comparison["round"])
        self.assertEqual(80, round_comparison["baselineScore"])
        self.assertEqual(120, round_comparison["candidateScore"])
        self.assertEqual(40, round_comparison["scoreDelta"])
        self.assertEqual(0, round_comparison["baselineFirstPlaces"])
        self.assertEqual(1, round_comparison["candidateFirstPlaces"])
        self.assertEqual(1, round_comparison["firstPlacesDelta"])
        self.assertAlmostEqual(0.2, round_comparison["baselineAccuracy"])
        self.assertAlmostEqual(0.3, round_comparison["candidateAccuracy"])
        self.assertAlmostEqual(0.1, round_comparison["accuracyDelta"])

    def test_paired_filtered_separates_unpaired_rounds_from_glitch_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root / "baseline" / "run-01",
                [
                    {"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1},
                    {"round": 2, "score": 180, "survival": 50, "bulletDamage": 120, "ramDamage": 0, "firstPlaces": 1},
                ],
                [
                    [_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(2)],
                    [_fired(2, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(8)],
                ],
            )
            _write_run(
                root / "candidate" / "run-01",
                [{"round": 1, "score": 120, "survival": 50, "bulletDamage": 60, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(2)]],
            )

            summary = analyze_experiment([root])

        pair = summary["pairedFiltered"]["pairs"][0]
        self.assertEqual([1], pair["validRounds"])
        self.assertEqual([], pair["baselineExcludedRounds"])
        self.assertEqual([], pair["candidateExcludedRounds"])
        self.assertEqual([2], pair["baselineUnpairedRounds"])
        self.assertEqual([], pair["candidateUnpairedRounds"])
        self.assertEqual(0, summary["pairedFiltered"]["baseline"]["excludedRounds"])
        self.assertEqual(1, summary["pairedFiltered"]["baseline"]["unpairedRounds"])

    def test_paired_filtered_marks_zero_valid_round_pairs_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root / "baseline" / "run-01",
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(8)]],
            )
            _write_run(
                root / "candidate" / "run-01",
                [{"round": 1, "score": 120, "survival": 50, "bulletDamage": 60, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster") for _ in range(10)] + [_hit("dynamic_cluster") for _ in range(8)]],
            )

            summary = analyze_experiment([root])

        self.assertFalse(summary["pairedFiltered"]["available"])
        self.assertEqual(1, summary["pairedFiltered"]["pairCount"])
        self.assertNotIn("delta", summary["pairedFiltered"])
        self.assertEqual([], summary["pairedFiltered"]["pairs"][0]["validRounds"])
        self.assertEqual([1], summary["pairedFiltered"]["pairs"][0]["baselineExcludedRounds"])
        self.assertEqual([1], summary["pairedFiltered"]["pairs"][0]["candidateExcludedRounds"])
        self.assertTrue(any("no valid pairedFiltered rounds" in warning for warning in summary["warnings"]))

    def test_paired_filtered_marks_no_matching_pairs_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root / "baseline" / "run-01",
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster"), _hit("dynamic_cluster", bullet_id=1)]],
            )

            summary = analyze_experiment([root])

        self.assertFalse(summary["pairedFiltered"]["available"])
        self.assertEqual(0, summary["pairedFiltered"]["pairCount"])
        self.assertNotIn("delta", summary["pairedFiltered"])
        self.assertTrue(any("no baseline/candidate pairs" in warning for warning in summary["warnings"]))

    def test_paired_filtered_does_not_collide_across_multiple_roots(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            roots = [Path(first_dir), Path(second_dir)]
            for index, root in enumerate(roots, start=1):
                _write_run(
                    root / "baseline" / "run-01",
                    [
                        {
                            "round": 1,
                            "score": index * 100,
                            "survival": 50,
                            "bulletDamage": 40,
                            "ramDamage": 0,
                            "firstPlaces": 1,
                        }
                    ],
                    [
                        [_fired(bullet_id, "dynamic_cluster") for bullet_id in range(10)]
                        + [_hit("dynamic_cluster", bullet_id=bullet_id) for bullet_id in range(2)]
                    ],
                )
                _write_run(
                    root / "candidate" / "run-01",
                    [
                        {
                            "round": 1,
                            "score": index * 100 + 10,
                            "survival": 50,
                            "bulletDamage": 50,
                            "ramDamage": 0,
                            "firstPlaces": 1,
                        }
                    ],
                    [
                        [_fired(bullet_id, "dynamic_cluster") for bullet_id in range(10)]
                        + [_hit("dynamic_cluster", bullet_id=bullet_id) for bullet_id in range(2)]
                    ],
                )

            summary = analyze_experiment(roots)

        self.assertTrue(summary["pairedFiltered"]["available"])
        self.assertEqual(2, summary["pairedFiltered"]["pairCount"])
        self.assertEqual(300, summary["pairedFiltered"]["baseline"]["score"])
        self.assertEqual(320, summary["pairedFiltered"]["candidate"]["score"])
        self.assertEqual(20, summary["pairedFiltered"]["delta"]["score"])

    def test_reports_missing_required_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "baseline" / "run-01"
            run_dir.mkdir(parents=True)
            _write_runner_log(
                run_dir,
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
            )

            summary = analyze_run(run_dir)

        self.assertIn("missing telemetry directory", summary.warnings)

    def test_reports_wrong_target_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "baseline" / "run-01"
            _write_run(
                run_dir,
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster"), _hit("dynamic_cluster", bullet_id=1)]],
            )

            summary = analyze_run(run_dir, target_name="Wrong_Bot")

        self.assertIn("no matching runner score rows", summary.warnings)

    def test_attributes_dynamic_hits_by_bullet_id_when_hit_mode_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "candidate" / "run-01"
            _write_run(
                run_dir,
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(7, "dynamic_cluster"), _hit(None, bullet_id=7)]],
            )

            summary = analyze_run(run_dir)

        self.assertEqual(1, summary.raw.dynamicShots)
        self.assertEqual(1, summary.raw.dynamicHits)

    def test_attributes_dynamic_hits_when_hit_precedes_fired_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "candidate" / "run-01"
            _write_run(
                run_dir,
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_hit(None, bullet_id=7), _fired(7, "dynamic_cluster")]],
            )

            summary = analyze_run(run_dir)

        self.assertEqual(1, summary.raw.hits)
        self.assertEqual(1, summary.raw.dynamicHits)

    def test_discovers_incomplete_run_dirs_for_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            telemetry_only = root / "baseline" / "run-01" / "telemetry"
            telemetry_only.mkdir(parents=True)
            (telemetry_only / "adaptive-prime-test.jsonl").write_text("", encoding="utf-8")

            run_dirs = discover_run_dirs([root])
            summary = analyze_experiment([root])

        self.assertEqual([telemetry_only.parent], run_dirs)
        self.assertEqual(1, summary["runCount"])
        self.assertTrue(any("missing runner.log" in warning for warning in summary["warnings"]))

    def test_nested_matchup_directory_is_not_counted_as_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "baseline" / "basic-gf-surfer" / "run-01"
            _write_run(
                run_dir,
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster"), _hit("dynamic_cluster", bullet_id=1)]],
            )

            run_dirs = discover_run_dirs([root])

        self.assertEqual([run_dir], run_dirs)

    def test_warns_on_short_basic_gf_surfer_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "candidate" / "run-01"
            _write_run(
                run_dir,
                [{"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}],
                [[_fired(1, "dynamic_cluster"), _hit("dynamic_cluster", bullet_id=1)]],
            )

            summary = analyze_run(run_dir)

        self.assertTrue(any("20+" in warning for warning in summary.warnings))

    def test_warns_when_telemetry_has_no_bullet_fired_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "candidate" / "run-01"
            cumulative_results = [
                {
                    "round": round_number,
                    "score": round_number * 10,
                    "survival": round_number * 5,
                    "bulletDamage": round_number * 4,
                    "ramDamage": 0,
                    "firstPlaces": round_number,
                }
                for round_number in range(1, 21)
            ]
            _write_run(run_dir, cumulative_results, [[] for _ in cumulative_results])

            summary = analyze_run(run_dir)

        self.assertIn("no bullet.fired telemetry", summary.warnings)
        self.assertTrue(any("scored rounds without shot telemetry" in warning for warning in summary.warnings))

    def test_rejects_threshold_outside_accuracy_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                analyze_experiment([Path(temp_dir)], threshold=80)

    def test_threshold_excludes_only_accuracy_above_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "baseline" / "run-01"
            _write_run(
                run_dir,
                [
                    {"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1},
                    {"round": 2, "score": 200, "survival": 100, "bulletDamage": 80, "ramDamage": 0, "firstPlaces": 2},
                ],
                [
                    [_fired(index, "dynamic_cluster") for index in range(10)]
                    + [_hit("dynamic_cluster", bullet_id=index) for index in range(3)],
                    [_fired(index, "dynamic_cluster") for index in range(10, 20)]
                    + [_hit("dynamic_cluster", bullet_id=index) for index in range(10, 14)],
                ],
            )

            summary = analyze_run(run_dir, threshold=0.30)

        self.assertFalse(summary.rounds[0].excludedGlitch)
        self.assertTrue(summary.rounds[1].excludedGlitch)

    def test_aggregates_dynamic_wave_diagnostics_with_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "baseline" / "run-01"
            _write_run(
                run_dir,
                [
                    {"round": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1},
                    {"round": 2, "score": 200, "survival": 100, "bulletDamage": 80, "ramDamage": 0, "firstPlaces": 2},
                ],
                [
                    [_fired(index, "dynamic_cluster") for index in range(10)]
                    + [_hit("dynamic_cluster", bullet_id=index) for index in range(5)]
                    + [
                        _wave_visit(
                            0.5,
                            0.1,
                            ambiguous=True,
                            confidence=0.2,
                            peak_ratio=0.9,
                            bandwidth=0.3,
                            shot_quality=0.2,
                        )
                    ],
                    [_fired(index, "dynamic_cluster") for index in range(10, 20)]
                    + [_hit("dynamic_cluster", bullet_id=index) for index in range(10, 12)]
                    + [
                        _wave_visit(
                            0.1,
                            0.2,
                            ambiguous=False,
                            confidence=0.8,
                            peak_ratio=0.4,
                            bandwidth=0.1,
                            shot_quality=0.6,
                        )
                    ],
                ],
            )

            summary = analyze_run(run_dir, threshold=0.30)

        self.assertEqual(2, summary.raw.dynamicWaveVisits)
        self.assertAlmostEqual(0.15, summary.raw.dynamicAvgError)
        self.assertAlmostEqual(0.25, summary.raw.dynamicAvgAbsError)
        self.assertAlmostEqual(0.5, summary.raw.dynamicAmbiguousRate)
        self.assertAlmostEqual(0.5, summary.raw.dynamicAvgAimConfidence)
        self.assertAlmostEqual(0.65, summary.raw.dynamicAvgPeakScoreRatio)
        self.assertAlmostEqual(0.2, summary.raw.dynamicAvgEffectiveBandwidth)
        self.assertAlmostEqual(0.4, summary.raw.dynamicAvgShotQuality)
        self.assertEqual(1, summary.filtered.dynamicWaveVisits)
        self.assertAlmostEqual(-0.1, summary.filtered.dynamicAvgError)
        self.assertAlmostEqual(0.1, summary.filtered.dynamicAvgAbsError)
        self.assertAlmostEqual(0.0, summary.filtered.dynamicAmbiguousRate)


def _write_run(
    run_dir: Path,
    cumulative_results: list[dict[str, int]],
    round_events: list[list[dict[str, object]]],
) -> None:
    telemetry_dir = run_dir / "telemetry"
    telemetry_dir.mkdir(parents=True)
    _write_runner_log(run_dir, cumulative_results)
    (run_dir / "results.json").write_text("{}\n", encoding="utf-8")

    events: list[dict[str, object]] = [
        {"bot": "adaptive-prime", "event": "battle.reset", "fields": {"rounds": len(round_events)}, "turn": None}
    ]
    for index, events_for_round in enumerate(round_events):
        if index > 0:
            events.append({"bot": "adaptive-prime", "event": "round.reset", "fields": {}, "turn": None})
        events.extend(events_for_round)
    with (telemetry_dir / "adaptive-prime-test.jsonl").open("w", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")


def _fired(bullet_id: int, aim_mode: str) -> dict[str, object]:
    return {"bot": "adaptive-prime", "event": "bullet.fired", "fields": {"bullet_id": bullet_id, "aim_mode": aim_mode}, "turn": 10}


def _hit(aim_mode: str | None, *, bullet_id: int | None = None) -> dict[str, object]:
    fields: dict[str, object] = {}
    if aim_mode is not None:
        fields["aim_mode"] = aim_mode
    if bullet_id is not None:
        fields["bullet_id"] = bullet_id
    return {"bot": "adaptive-prime", "event": "bullet.hit_bot", "fields": fields, "turn": 20}


def _wave_visit(
    actual_guess_factor: float,
    selected_guess_factor: float,
    *,
    ambiguous: bool,
    confidence: float,
    peak_ratio: float,
    bandwidth: float,
    shot_quality: float = 0.5,
) -> dict[str, object]:
    return {
        "bot": "adaptive-prime",
        "event": "gun.wave_visit",
        "fields": {
            "guess_factor": actual_guess_factor,
            "selected_gun": "dynamic_cluster",
            "dynamic_cluster_selected_guess_factor": selected_guess_factor,
            "dynamic_cluster_ambiguous_peak": ambiguous,
            "dynamic_cluster_aim_confidence": confidence,
            "dynamic_cluster_peak_score_ratio": peak_ratio,
            "dynamic_cluster_effective_bandwidth": bandwidth,
            "dynamic_cluster_shot_quality": shot_quality,
        },
        "turn": 30,
    }


def _write_runner_log(run_dir: Path, cumulative_results: list[dict[str, int]]) -> None:
    runner_lines = [
        f"at=2026-07-03T00:00:00Z event=run.start rounds={len(cumulative_results)} gameType=ONE_VS_ONE bots=2"
    ]
    for result in cumulative_results:
        runner_lines.append(f"at=2026-07-03T00:00:00Z event=round.started round={result['round']}")
        runner_lines.append(f"at=2026-07-03T00:00:00Z event=round.ended round={result['round']} turn=100 results=2")
        runner_lines.append(
            "at=2026-07-03T00:00:00Z event=round.result round={round} rank=1 name=Adaptive_Prime "
            "score={score} survival={survival} bulletDamage={bulletDamage} ramDamage={ramDamage} "
            "firstPlaces={firstPlaces}".format(**result)
        )
        runner_lines.append(
            "at=2026-07-03T00:00:00Z event=round.result round={round} rank=2 name=BasicGFSurfer "
            "score=0 survival=0 bulletDamage=0 ramDamage=0 firstPlaces=0".format(**result)
        )
    (run_dir / "runner.log").write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
