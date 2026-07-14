import os
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path

from bot_core.async_writer import AsyncItemWriter
from bot_core.debug import DebugLogger, FiredBulletTracker


class _DummyBot:
    turn_number = 12


class _SlowStringIO(StringIO):
    def write(self, text: str) -> int:
        time.sleep(0.0001)
        return super().write(text)


class DebugLoggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._previous_env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._previous_env)

    def test_debug_logger_flushes_async_log_on_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ROBOCODE_DEBUG"] = "1"
            os.environ["ROBOCODE_LOG_DIR"] = tmpdir
            os.environ.pop("ROBOCODE_TELEMETRY", None)

            logger = DebugLogger(_DummyBot(), "test-bot")
            logger.log("track", target=7, distance=250)
            logger.close()

            log_files = list(Path(tmpdir).glob("test-bot-*.log"))
            self.assertEqual(1, len(log_files))
            self.assertEqual("turn=12 event=track target=7 distance=250\n", log_files[0].read_text(encoding="utf-8"))

    def test_debug_sync_mode_writes_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ROBOCODE_DEBUG"] = "1"
            os.environ["ROBOCODE_DEBUG_SYNC"] = "1"
            os.environ["ROBOCODE_LOG_DIR"] = tmpdir
            os.environ.pop("ROBOCODE_TELEMETRY", None)

            logger = DebugLogger(_DummyBot(), "test-bot")
            logger.log("track", target=7)

            log_file = list(Path(tmpdir).glob("test-bot-*.log"))[0]
            self.assertEqual("turn=12 event=track target=7\n", log_file.read_text(encoding="utf-8"))
            logger.close()

    def test_async_debug_writer_drops_when_queue_is_full(self) -> None:
        stream = _SlowStringIO()
        writer = AsyncItemWriter(stream, str, queue_size=1)

        for index in range(5000):
            writer.submit(f"line {index}\n")
        dropped_count = writer.dropped_count
        if dropped_count:
            writer.submit_blocking(f"turn=12 event=debug.dropped count={dropped_count}\n")
        writer.close()

        self.assertGreater(dropped_count, 0)
        self.assertIn("event=debug.dropped", stream.getvalue())

    def test_default_queue_size_is_large_burst_buffer(self) -> None:
        os.environ.pop("ROBOCODE_DEBUG_QUEUE_SIZE", None)

        self.assertEqual(8192, DebugLogger._int_env("ROBOCODE_DEBUG_QUEUE_SIZE", 8192))

    def test_sampling_throttles_each_event_independently_at_interval_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ROBOCODE_DEBUG"] = "1"
            os.environ["ROBOCODE_DEBUG_SYNC"] = "1"
            os.environ["ROBOCODE_LOG_DIR"] = tmpdir
            os.environ.pop("ROBOCODE_TELEMETRY", None)
            bot = _DummyBot()
            logger = DebugLogger(bot, "test-bot", sample_interval=25)

            bot.turn_number = 0
            logger.sample("movement.goto_surf", target=7)
            logger.sample("track", target=7)
            bot.turn_number = 24
            logger.sample("movement.goto_surf", target=7)
            logger.sample("track", target=7)
            bot.turn_number = 25
            logger.sample("movement.goto_surf", target=7)
            logger.sample("track", target=7)
            logger.close()

            log_file = list(Path(tmpdir).glob("test-bot-*.log"))[0]
            self.assertEqual(
                [
                    "turn=0 event=movement.goto_surf target=7",
                    "turn=0 event=track target=7",
                    "turn=25 event=movement.goto_surf target=7",
                    "turn=25 event=track target=7",
                ],
                log_file.read_text(encoding="utf-8").splitlines(),
            )

    def test_sampling_windows_restart_when_any_event_observes_new_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ROBOCODE_DEBUG"] = "1"
            os.environ["ROBOCODE_DEBUG_SYNC"] = "1"
            os.environ["ROBOCODE_LOG_DIR"] = tmpdir
            os.environ.pop("ROBOCODE_TELEMETRY", None)
            bot = _DummyBot()
            logger = DebugLogger(bot, "test-bot", sample_interval=25)

            bot.turn_number = 0
            logger.sample("track", target=7)
            bot.turn_number = 10
            logger.sample("conditional", target=7)
            bot.turn_number = 0
            logger.log("round.reset")
            logger.sample("track", target=7)
            bot.turn_number = 5
            logger.sample("conditional", target=7)
            logger.close()

            log_file = list(Path(tmpdir).glob("test-bot-*.log"))[0]
            self.assertEqual(
                [
                    "turn=0 event=track target=7",
                    "turn=10 event=conditional target=7",
                    "turn=0 event=round.reset ",
                    "turn=0 event=track target=7",
                    "turn=5 event=conditional target=7",
                ],
                log_file.read_text(encoding="utf-8").splitlines(),
            )

    def test_fired_bullet_tracker_clear_removes_round_local_attribution(self) -> None:
        tracker = FiredBulletTracker()
        tracker.record(17, aim_mode="linear")

        tracker.clear()

        self.assertEqual({}, tracker.fields_for(17))


if __name__ == "__main__":
    unittest.main()
