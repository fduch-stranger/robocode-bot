import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "tools" / "telemetry_viewer" / "server.py"

spec = importlib.util.spec_from_file_location("telemetry_viewer_server", SERVER_PATH)
assert spec is not None
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def _event(bot: str, name: str, pid: int, ts: float, fields: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "bot": bot,
        "event": name,
        "fields": fields or {},
        "pid": pid,
        "ts": ts,
        "turn": None if name == "telemetry.session" else 1,
    }


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events), encoding="utf-8")


class TelemetryViewerServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._reset_handler_state()

    def tearDown(self) -> None:
        self._reset_handler_state()

    def test_new_pid_for_existing_bot_starts_new_viewer_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            _write_jsonl(
                telemetry_dir / "adaptive-prime-100.jsonl",
                [_event("adaptive-prime", "telemetry.session", 100, 1.0, {"pid": 100}), _event("adaptive-prime", "track", 100, 1.1)],
            )
            first = handler._events({})

            _write_jsonl(
                telemetry_dir / "adaptive-prime-200.jsonl",
                [_event("adaptive-prime", "telemetry.session", 200, 2.0, {"pid": 200}), _event("adaptive-prime", "track", 200, 2.1)],
            )
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertGreater(second["generation"], first["generation"])
        self.assertTrue(second["truncated"])
        self.assertEqual({"adaptive-prime-200.jsonl"}, {event["file"] for event in second["events"]})

    def test_late_session_without_matching_bot_replaces_stale_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            _write_jsonl(
                telemetry_dir / "adaptive-prime-100.jsonl",
                [_event("adaptive-prime", "telemetry.session", 100, 1.0, {"pid": 100}), _event("adaptive-prime", "track", 100, 1.1)],
            )
            first = handler._events({})

            _write_jsonl(
                telemetry_dir / "circle-strafer-300.jsonl",
                [_event("circle-strafer", "telemetry.session", 300, 20.0, {"pid": 300}), _event("circle-strafer", "track", 300, 20.1)],
            )
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertGreater(second["generation"], first["generation"])
        self.assertEqual(["circle-strafer"], sorted({event["bot"] for event in second["events"]}))

    def test_late_events_from_old_files_do_not_reenter_new_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            _write_jsonl(
                telemetry_dir / "chase-lock-100.jsonl",
                [_event("chase-lock", "telemetry.session", 100, 1.0, {"pid": 100}), _event("chase-lock", "track", 100, 1.1)],
            )
            first = handler._events({})

            _write_jsonl(
                telemetry_dir / "circle-strafer-200.jsonl",
                [_event("circle-strafer", "telemetry.session", 200, 2.0, {"pid": 200}), _event("circle-strafer", "track", 200, 2.1)],
            )
            with (telemetry_dir / "chase-lock-100.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event("chase-lock", "hit.bullet", 100, 2.2), separators=(",", ":")) + "\n")
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertGreater(second["generation"], first["generation"])
        self.assertEqual(["circle-strafer"], sorted({event["bot"] for event in second["events"]}))

    def test_short_round_reset_keeps_viewer_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            path = telemetry_dir / "chase-lock-100.jsonl"
            _write_jsonl(
                path,
                [
                    _event("chase-lock", "telemetry.session", 100, 1.0, {"pid": 100}),
                    _event("chase-lock", "track", 100, 1.1),
                ],
            )
            first = handler._events({})

            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        _event("chase-lock", "round.reset", 100, 1.2, {"previous_turn": 8, "current_turn": 1}),
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                stream.write(json.dumps(_event("chase-lock", "track", 100, 1.3), separators=(",", ":")) + "\n")
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertEqual(second["generation"], first["generation"])
        self.assertFalse(second["truncated"])
        self.assertEqual(["round.reset", "track"], [event["event"] for event in second["events"]])

    def test_battle_reset_starts_new_generation_for_same_file_and_pid(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            path = telemetry_dir / "adaptive-prime-100.jsonl"
            _write_jsonl(
                path,
                [
                    _event("adaptive-prime", "telemetry.session", 100, 1.0, {"pid": 100}),
                    _event("adaptive-prime", "track", 100, 1.1),
                ],
            )
            first = handler._events({})

            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event("adaptive-prime", "battle.reset", 100, 2.0), separators=(",", ":")) + "\n")
                stream.write(json.dumps(_event("adaptive-prime", "track", 100, 2.1), separators=(",", ":")) + "\n")
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertGreater(second["generation"], first["generation"])
        self.assertTrue(second["truncated"])
        self.assertEqual(["battle.reset", "track"], [event["event"] for event in second["events"]])

    def test_multiple_battle_reset_events_share_new_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            adaptive = telemetry_dir / "adaptive-prime-100.jsonl"
            chase = telemetry_dir / "chase-lock-200.jsonl"
            _write_jsonl(
                adaptive,
                [_event("adaptive-prime", "telemetry.session", 100, 1.0, {"pid": 100}), _event("adaptive-prime", "track", 100, 1.1)],
            )
            _write_jsonl(
                chase,
                [_event("chase-lock", "telemetry.session", 200, 1.0, {"pid": 200}), _event("chase-lock", "track", 200, 1.1)],
            )
            first = handler._events({})

            with adaptive.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event("adaptive-prime", "battle.reset", 100, 2.0), separators=(",", ":")) + "\n")
            with chase.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event("chase-lock", "battle.reset", 200, 2.0), separators=(",", ":")) + "\n")
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertGreater(second["generation"], first["generation"])
        self.assertEqual(["adaptive-prime", "chase-lock"], sorted({event["bot"] for event in second["events"]}))
        self.assertEqual(["battle.reset"], sorted({event["event"] for event in second["events"]}))

    def test_interleaved_battle_resets_share_new_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            adaptive = telemetry_dir / "adaptive-prime-100.jsonl"
            chase = telemetry_dir / "chase-lock-200.jsonl"
            _write_jsonl(
                adaptive,
                [_event("adaptive-prime", "telemetry.session", 100, 1.0, {"pid": 100}), _event("adaptive-prime", "track", 100, 1.1)],
            )
            _write_jsonl(
                chase,
                [_event("chase-lock", "telemetry.session", 200, 1.0, {"pid": 200}), _event("chase-lock", "track", 200, 1.1)],
            )
            first = handler._events({})

            with adaptive.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event("adaptive-prime", "battle.reset", 100, 2.0), separators=(",", ":")) + "\n")
                stream.write(json.dumps(_event("adaptive-prime", "track", 100, 2.1), separators=(",", ":")) + "\n")
            with chase.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_event("chase-lock", "battle.reset", 200, 2.2), separators=(",", ":")) + "\n")
                stream.write(json.dumps(_event("chase-lock", "track", 200, 2.3), separators=(",", ":")) + "\n")
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertGreater(second["generation"], first["generation"])
        self.assertEqual(
            ["adaptive-prime:battle.reset", "adaptive-prime:track", "chase-lock:battle.reset", "chase-lock:track"],
            [f"{event['bot']}:{event['event']}" for event in second["events"]],
        )

    def test_normal_round_reset_keeps_viewer_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp)
            handler = self._handler(telemetry_dir)
            path = telemetry_dir / "adaptive-prime-100.jsonl"
            _write_jsonl(
                path,
                [
                    _event("adaptive-prime", "telemetry.session", 100, 1.0, {"pid": 100}),
                    _event("adaptive-prime", "track", 100, 1.1),
                ],
            )
            first = handler._events({})

            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        _event("adaptive-prime", "round.reset", 100, 1.2, {"previous_turn": 283, "current_turn": 1}),
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            second = handler._events({"cursor": [str(first["cursor"])], "generation": [str(first["generation"])]})

        self.assertEqual(second["generation"], first["generation"])
        self.assertFalse(second["truncated"])

    @staticmethod
    def _handler(telemetry_dir: Path) -> Any:
        server.TelemetryHandler.telemetry_dir = telemetry_dir
        server.TelemetryHandler.static_dir = ROOT / "tools" / "telemetry_viewer" / "static"
        return object.__new__(server.TelemetryHandler)

    @staticmethod
    def _reset_handler_state() -> None:
        server.TelemetryHandler._event_cache.clear()
        server.TelemetryHandler._positions.clear()
        server.TelemetryHandler._active_files.clear()
        server.TelemetryHandler._next_cursor = 1
        server.TelemetryHandler._generation = 1
        server.TelemetryHandler._battle_reset_group_timestamp = None


if __name__ == "__main__":
    unittest.main()
