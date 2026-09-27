import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from bot_core.advisors.client import AdvisorClient
from bot_core.advisors.jev_transport import JevTransport
from bot_core.movement import MovementWave

ROOT = Path(__file__).resolve().parents[1]
JEV_DIR = ROOT / "bots" / "adaptive-jev"
FAKE_KEY = "fake-typesafe-key-5d9c-never-logged"
ALLOWED_PASSTHROUGH_ATTRIBUTES = {
    "__module__",
    "__qualname__",
    "__doc__",
    "__init__",
    "__firstlineno__",
    "__static_attributes__",
    "_abc_impl",
    "__abstractmethods__",
}


def _load_adaptive_jev() -> ModuleType:
    name = "_test_adaptive_jev"
    if name in sys.modules:
        return sys.modules[name]
    if str(JEV_DIR) not in sys.path:
        sys.path.insert(0, str(JEV_DIR))
    spec = importlib.util.spec_from_file_location(name, JEV_DIR / "adaptive-jev.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status = 200
    will_close = False

    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str) -> None:
        return None


class EchoConnection:
    """Answers every question with its first option; records the headers it was sent."""

    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []
        self._questions: dict = {}

    def request(self, method, path, body=None, headers=None) -> None:
        self.headers.append(dict(headers or {}))
        self._questions = json.loads(body)["questions"]

    def getresponse(self) -> FakeResponse:
        answers = {
            question_id: {
                "type": "choice",
                "choice": next(iter(question["criteria"])),
                "probabilities": {option: 1.0 / len(question["criteria"]) for option in question["criteria"]},
                "confidence": 0.5,
            }
            for question_id, question in self._questions.items()
        }
        return FakeResponse({"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 10}})

    def close(self) -> None:
        pass


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))

    def sample(self, event: str, **fields: object) -> None:
        self.log(event, **fields)


class FakeBot:
    enemy_count = 1
    round_number = 1
    arena_width = 800.0
    arena_height = 600.0

    def __init__(self) -> None:
        self.turn_number = 0
        self.x, self.y, self.direction, self.speed = 100.0, 300.0, 90.0, 8.0


class AdaptiveJevTest(unittest.TestCase):
    def setUp(self) -> None:
        self._previous_env = os.environ.copy()
        for name in list(os.environ):
            if name.startswith(("ROBOCODE_JEV_", "ROBOCODE_TELEMETRY", "TYPESAFE_")):
                os.environ.pop(name)
        self.module = _load_adaptive_jev()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._previous_env)

    def test_disabled_bot_is_adaptive_prime_with_only_a_new_name(self) -> None:
        module = self.module
        self.assertTrue(issubclass(module.AdaptiveJevPassthrough, module.AdaptivePrime))
        self.assertEqual(set(), set(vars(module.AdaptiveJevPassthrough)) - ALLOWED_PASSTHROUGH_ATTRIBUTES)

        def fail(config):
            raise AssertionError("the advisor must not be constructed when disabled")

        bot = module.build_bot(module.load_jev_config({}), transport_factory=fail)
        self.assertIs(type(bot), module.AdaptiveJevPassthrough)
        self.assertFalse(hasattr(bot, "_advisor"))

    def test_missing_key_falls_back_to_adaptive_prime(self) -> None:
        config = self.module.load_jev_config({"ROBOCODE_JEV_ENABLED": "1"})
        bot = self.module.build_bot(config, transport_factory=lambda config: None)
        self.assertIs(type(bot), self.module.AdaptiveJevPassthrough)

    def test_enabled_bot_keeps_adaptive_prime_movement_config(self) -> None:
        config = self.module.load_jev_config({"ROBOCODE_JEV_ENABLED": "1", "ROBOCODE_JEV_TRANSPORT": "stub"})
        bot = self.module.build_bot(config)
        try:
            self.assertIs(type(bot), self.module.AdaptiveJev)
            self.assertIs(self.module.MOVEMENT_FLATTENING_CONFIG, bot._movement.config)
        finally:
            bot._advisor.close()

    def test_config_parsing(self) -> None:
        config = self.module.load_jev_config(
            {"ROBOCODE_JEV_ENABLED": "yes", "ROBOCODE_JEV_MODE": "active", "ROBOCODE_JEV_PHASES": "surf, style,bogus"}
        )
        self.assertEqual((True, "active", ("style", "surf")), (config.enabled, config.mode, config.phases))
        self.assertEqual(("style",), self.module.load_jev_config({"ROBOCODE_JEV_PHASES": "bogus"}).phases)

    def test_api_key_never_reaches_telemetry(self) -> None:
        os.environ["TYPESAFE_API_KEY"] = FAKE_KEY
        connection = EchoConnection()
        transport = JevTransport(os.environ["TYPESAFE_API_KEY"], connection_factory=lambda *args: connection)
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ.update({"ROBOCODE_TELEMETRY": "1", "ROBOCODE_TELEMETRY_DIR": tmpdir, "ROBOCODE_TELEMETRY_SYNC": "1"})
            config = self.module.load_jev_config({"ROBOCODE_JEV_ENABLED": "1", "ROBOCODE_JEV_PHASES": "style,surf"})
            bot = self.module.build_bot(config, transport_factory=lambda config: transport)
            bot._advisor.close()
            bot._debug.close()
            written = "".join(path.read_text(encoding="utf-8") for path in Path(tmpdir).rglob("*"))
        self.assertIn("advisor.config", written)
        self.assertNotIn(FAKE_KEY, written)

        # Drive the layer through a style question, a surf question, and a surf outcome.
        from jev_advisor import JevAdvisorLayer
        from bot_core.telemetry.advisor import AdvisorTelemetry

        sink = CapturingSink()
        fake_bot = FakeBot()
        client = AdvisorClient(transport, max_rps=100.0, start=False)
        layer = JevAdvisorLayer(fake_bot, config, client, AdvisorTelemetry(sink))
        for turn in range(1, 131):
            fake_bot.turn_number = turn
            layer.on_scan(2, 500.0, 300.0, 0.0, 8.0 if turn % 40 < 20 else -8.0)
            layer.on_turn_end()
        wave = MovementWave(2, 500.0, 300.0, 180.0, 1, 14.0, 30.0, 30.0, 129, 2)
        layer.on_enemy_wave(fake_bot, wave)
        layer.on_wave_visit(fake_bot, wave, 0.4, True)
        while client.process_next():
            pass
        fake_bot.turn_number = 140
        layer.on_turn_end()
        layer.close()

        names = [name for name, _fields in sink.events]
        for expected in ("advisor.request", "advisor.answer", "advisor.outcome", "advisor.stats"):
            self.assertIn(expected, names)
        self.assertNotIn("advisor.error", names)
        self.assertNotIn(FAKE_KEY, json.dumps(sink.events, default=str))
        self.assertEqual(f"Bearer {FAKE_KEY}", connection.headers[0]["Authorization"])


if __name__ == "__main__":
    unittest.main()
