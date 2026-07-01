import json
import time
import unittest
from io import StringIO

from bot_core.telemetry.recorder import TelemetryRecorder


class _DummyBot:
    turn_number = 42
    x = 100.1234
    y = 200.5678
    energy = 88.8
    direction = 90
    gun_direction = 91
    radar_direction = 92
    speed = 4
    target_speed = 8
    turn_rate = 1
    gun_turn_rate = 2
    radar_turn_rate = 3
    gun_heat = 0.4
    gun_cooling_rate = 0.1
    enemy_count = 1
    arena_width = 800
    arena_height = 600


def _records(stream: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


class TelemetryRecorderTest(unittest.TestCase):
    def test_async_recorder_flushes_records_on_close(self) -> None:
        stream = StringIO()
        recorder = TelemetryRecorder(_DummyBot(), "test-bot", stream, sync=False, queue_size=8)

        recorder.write("track", {"target": 7, "distance": 250.123456, "gun_bearing": 1.2, "aim_mode": "linear"})
        recorder.close()

        records = _records(stream)
        self.assertEqual(["telemetry.session", "track"], [record["event"] for record in records])
        self.assertEqual("test-bot", records[1]["bot"])
        self.assertEqual(42, records[1]["turn"])
        self.assertEqual(100.123, records[1]["state"]["x"])
        self.assertEqual(250.123456, records[1]["fields"]["distance"])

    def test_async_recorder_drops_when_queue_is_full_instead_of_blocking(self) -> None:
        stream = StringIO()
        recorder = TelemetryRecorder(_DummyBot(), "test-bot", stream, sync=False, queue_size=1)

        for index in range(5000):
            recorder.write("track", {"target": index, "distance": 100, "gun_bearing": 0, "aim_mode": "linear"})
        recorder.close()

        records = _records(stream)
        events = [record["event"] for record in records]
        self.assertIn("telemetry.dropped", events)
        dropped = [record for record in records if record["event"] == "telemetry.dropped"][0]
        self.assertGreater(dropped["fields"]["count"], 0)
        self.assertLess(len(records), 5001)

    def test_sync_recorder_writes_and_flushes_immediately(self) -> None:
        stream = StringIO()
        recorder = TelemetryRecorder(_DummyBot(), "test-bot", stream, sync=True)

        recorder.write("track", {"target": 7, "distance": 250, "gun_bearing": 1.2, "aim_mode": "linear"})

        records_before_close = _records(stream)
        self.assertEqual(["telemetry.session", "track"], [record["event"] for record in records_before_close])

        recorder.close()
        self.assertEqual(records_before_close, _records(stream))

    def test_write_after_close_is_ignored(self) -> None:
        stream = StringIO()
        recorder = TelemetryRecorder(_DummyBot(), "test-bot", stream, sync=False, queue_size=8)

        recorder.close()
        before = stream.getvalue()
        recorder.write("track", {"target": 7, "distance": 250, "gun_bearing": 1.2, "aim_mode": "linear"})
        time.sleep(0.01)

        self.assertEqual(before, stream.getvalue())


if __name__ == "__main__":
    unittest.main()
