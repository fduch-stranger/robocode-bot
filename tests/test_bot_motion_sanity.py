import json
import tempfile
import unittest
from pathlib import Path

from tools import bot_motion_sanity


def bot_state_line(round_number: int, turn: int, name: str, x: float, y: float, speed: float, energy: float = 80.0) -> str:
    return (
        f"at=2026-07-04T12:00:00Z event=bot.state round={round_number} turn={turn} "
        f"id=2 name={name} energy={energy:.3f} x={x:.3f} y={y:.3f} direction=0.000 "
        f"gunDirection=0.000 radarDirection=0.000 speed={speed:.3f} turnRate=0.000 "
        "gunTurnRate=0.000 radarTurnRate=0.000 gunHeat=0.000 enemyCount=1\n"
    )


def round_result_line(
    round_number: int,
    name: str,
    score: int,
    survival: int,
    bullet_damage: int,
    first_places: int,
) -> str:
    return (
        f"at=2026-07-04T12:00:00Z event=round.result round={round_number} rank=1 name={name} "
        f"score={score} survival={survival} bulletDamage={bullet_damage} ramDamage=0 firstPlaces={first_places}\n"
    )


class BotMotionSanityTest(unittest.TestCase):
    def test_detects_live_bot_stationary_span(self) -> None:
        states = [
            bot_motion_sanity.BotState(1, 10, "LegacyReferenceBot", 100.0, 100.0, 0.0, 80.0),
            bot_motion_sanity.BotState(1, 60, "LegacyReferenceBot", 100.1, 100.0, 0.0, 79.0),
            bot_motion_sanity.BotState(1, 120, "LegacyReferenceBot", 100.1, 100.0, 0.0, 78.0),
        ]

        motions = bot_motion_sanity.analyze_motion(
            states,
            bot_filters={"LegacyReferenceBot"},
            stationary_distance=0.5,
            speed_threshold=0.05,
            max_stationary_turns=100,
            min_energy=0.1,
        )

        self.assertTrue(motions[0].suspect)
        self.assertEqual(0, motions[0].cleanRounds)
        self.assertEqual(1, motions[0].suspectRounds)
        self.assertEqual(110, motions[0].rounds[0].longestStationaryTurns)
        self.assertEqual(10, motions[0].rounds[0].stationaryStartTurn)
        self.assertEqual(120, motions[0].rounds[0].stationaryEndTurn)

    def test_movement_resets_stationary_span(self) -> None:
        states = [
            bot_motion_sanity.BotState(1, 10, "LegacyReferenceBot", 100.0, 100.0, 0.0, 80.0),
            bot_motion_sanity.BotState(1, 60, "LegacyReferenceBot", 100.0, 100.0, 0.0, 79.0),
            bot_motion_sanity.BotState(1, 100, "LegacyReferenceBot", 130.0, 100.0, 4.0, 78.0),
            bot_motion_sanity.BotState(1, 150, "LegacyReferenceBot", 130.0, 100.0, 0.0, 77.0),
        ]

        motions = bot_motion_sanity.analyze_motion(
            states,
            bot_filters=set(),
            stationary_distance=0.5,
            speed_threshold=0.05,
            max_stationary_turns=100,
            min_energy=0.1,
        )

        self.assertFalse(motions[0].suspect)
        self.assertEqual(1, motions[0].cleanRounds)
        self.assertEqual(0, motions[0].suspectRounds)
        self.assertEqual(50, motions[0].rounds[0].longestStationaryTurns)

    def test_cli_writes_json_and_returns_nonzero_for_suspect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = root / "runner.log"
            json_path = root / "motion.json"
            log_path.write_text(
                "".join(
                    [
                        bot_state_line(1, 10, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        bot_state_line(1, 70, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        bot_state_line(1, 130, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        round_result_line(1, "LegacyReferenceBot", 120, 50, 40, 1),
                        round_result_line(1, "BasicGFSurfer_Port", 80, 0, 80, 0),
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = bot_motion_sanity.main(
                [
                    str(log_path),
                    "--bot",
                    "LegacyReferenceBot",
                    "--max-stationary-turns",
                    "100",
                    "--json-output",
                    str(json_path),
                ]
            )

            self.assertEqual(1, exit_code)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual("suspect", payload["status"])
            self.assertEqual(0, payload["bots"][0]["cleanRounds"])
            self.assertEqual(1, payload["bots"][0]["suspectRounds"])
            self.assertEqual([1], payload["scoreSummary"]["excludedRounds"])

    def test_score_split_uses_per_round_deltas_and_excludes_suspect_rounds(self) -> None:
        scores = [
            bot_motion_sanity.RoundScore(1, "Port", 100, 50, 40, 0, 1),
            bot_motion_sanity.RoundScore(1, "Fixed", 90, 0, 90, 0, 0),
            bot_motion_sanity.RoundScore(2, "Port", 140, 50, 90, 0, 1),
            bot_motion_sanity.RoundScore(2, "Fixed", 20, 0, 20, 0, 0),
        ]

        split = bot_motion_sanity.score_split(scores, {2})

        assert split is not None
        by_bot = {bot["name"]: bot for bot in split["bots"]}
        self.assertEqual([2], split["excludedRounds"])
        self.assertEqual({"rounds": 1, "score": 100, "survival": 50, "bulletDamage": 40, "ramDamage": 0, "firstPlaces": 1}, by_bot["Port"]["clean"])
        self.assertEqual({"rounds": 1, "score": 140, "survival": 50, "bulletDamage": 90, "ramDamage": 0, "firstPlaces": 1}, by_bot["Port"]["suspect"])

    def test_round_score_parser_converts_cumulative_scores_to_round_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runner.log"
            log_path.write_text(
                "".join(
                    [
                        round_result_line(1, "Port", 100, 50, 40, 1),
                        round_result_line(2, "Port", 260, 100, 130, 2),
                    ]
                ),
                encoding="utf-8",
            )

            scores = bot_motion_sanity.parse_round_scores(log_path)

            self.assertEqual(2, len(scores))
            self.assertEqual(100, scores[0].score)
            self.assertEqual(160, scores[1].score)
            self.assertEqual(90, scores[1].bulletDamage)

    def test_discover_runner_logs_finds_nested_series_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "run-001" / "runner.log"
            second = root / "run-002" / "runner.log"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")

            self.assertEqual([first, second], bot_motion_sanity.discover_runner_logs(root))

    def test_cli_aggregates_directory_score_split(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clean_log = root / "run-001" / "runner.log"
            suspect_log = root / "run-002" / "runner.log"
            json_path = root / "motion.json"
            clean_log.parent.mkdir()
            suspect_log.parent.mkdir()
            clean_log.write_text(
                "".join(
                    [
                        bot_state_line(1, 10, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        bot_state_line(1, 70, "LegacyReferenceBot", 130.0, 100.0, 4.0),
                        bot_state_line(1, 130, "LegacyReferenceBot", 170.0, 100.0, 4.0),
                        round_result_line(1, "LegacyReferenceBot", 110, 50, 40, 1),
                        round_result_line(1, "BasicGFSurfer_Port", 100, 0, 100, 0),
                    ]
                ),
                encoding="utf-8",
            )
            suspect_log.write_text(
                "".join(
                    [
                        bot_state_line(1, 10, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        bot_state_line(1, 70, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        bot_state_line(1, 130, "LegacyReferenceBot", 100.0, 100.0, 0.0),
                        round_result_line(1, "LegacyReferenceBot", 0, 0, 0, 0),
                        round_result_line(1, "BasicGFSurfer_Port", 180, 50, 120, 1),
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = bot_motion_sanity.main(
                [
                    str(root),
                    "--bot",
                    "LegacyReferenceBot",
                    "--max-stationary-turns",
                    "100",
                    "--json-output",
                    str(json_path),
                    "--warn-only",
                ]
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual("suspect", payload["status"])
            self.assertEqual(2, len(payload["runs"]))
            by_bot = {bot["name"]: bot for bot in payload["scoreSummary"]["bots"]}
            self.assertEqual(100, by_bot["BasicGFSurfer_Port"]["clean"]["score"])
            self.assertEqual(180, by_bot["BasicGFSurfer_Port"]["suspect"]["score"])
            self.assertEqual(110, by_bot["LegacyReferenceBot"]["clean"]["score"])
            self.assertEqual(0, by_bot["LegacyReferenceBot"]["suspect"]["score"])

    def test_cli_returns_two_when_log_has_no_tick_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runner.log"
            log_path.write_text("at=2026-07-04T12:00:00Z event=round.started round=1\n", encoding="utf-8")

            self.assertEqual(2, bot_motion_sanity.main([str(log_path)]))


if __name__ == "__main__":
    unittest.main()
