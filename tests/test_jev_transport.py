import json
import unittest

from bot_core.advisors.jev_transport import AdvisorError, JevTransport

FAKE_KEY = "test-key-never-logged-7f3a"


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None, will_close: bool = False) -> None:
        self.status = status
        self._body = body
        self._headers = headers or {}
        self.will_close = will_close

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name)


class FakeConnection:
    def __init__(self, script: list[object], log: list[dict[str, object]]) -> None:
        self._script = script
        self._log = log
        self.closed = False

    def request(self, method, path, body=None, headers=None) -> None:
        self._log.append({"method": method, "path": path, "body": body, "headers": dict(headers or {})})
        outcome = self._script[0]
        if isinstance(outcome, BaseException):
            self._script.pop(0)
            raise outcome

    def getresponse(self) -> FakeResponse:
        return self._script.pop(0)

    def close(self) -> None:
        self.closed = True


def _transport(script: list[object], log: list[dict[str, object]], created: list[FakeConnection] | None = None) -> JevTransport:
    def factory(scheme, host, port, timeout_s, context):
        connection = FakeConnection(script, log)
        if created is not None:
            created.append(connection)
        return connection

    return JevTransport(FAKE_KEY, base_url="https://api.example.test", model="jev-1.13.0", connection_factory=factory)


def _ok(answers: dict[str, object]) -> FakeResponse:
    payload = {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 42, "output_tokens": 7}}
    return FakeResponse(200, json.dumps(payload).encode())


class JevTransportTest(unittest.TestCase):
    def test_posts_state_model_and_questions_with_bearer_key(self) -> None:
        log: list[dict[str, object]] = []
        transport = _transport([_ok({"q": {"type": "choice", "choice": "a"}})], log)
        response = transport.evaluate({"enemy": {"speed": "fast"}}, {"q": {"type": "choice", "criteria": {"a": None}}})

        self.assertEqual({"q": {"type": "choice", "choice": "a"}}, response.answers)
        self.assertEqual(("jev-1.13.0", 42), (response.model, response.input_tokens))
        sent = log[0]
        self.assertEqual(("POST", "/v1/systemone"), (sent["method"], sent["path"]))
        self.assertEqual(f"Bearer {FAKE_KEY}", sent["headers"]["Authorization"])
        body = json.loads(sent["body"])
        self.assertEqual({"state", "model", "questions"}, set(body))
        self.assertEqual("jev-1.13.0", body["model"])

    def test_http_errors_map_to_safe_kinds(self) -> None:
        cases = [
            (FakeResponse(401, b"{}"), "auth", False, None),
            (FakeResponse(422, b"{}"), "invalid_request", False, None),
            (FakeResponse(429, b"{}", {"Retry-After": "3"}), "rate_limited", True, 3.0),
            (FakeResponse(529, b"{}"), "overloaded", True, None),
            (FakeResponse(503, b"{}"), "server_error", False, None),
            (FakeResponse(200, b"not json"), "parse", False, None),
        ]
        for response, kind, throttled, retry_after in cases:
            with self.subTest(kind=kind):
                transport = _transport([response], [])
                with self.assertRaises(AdvisorError) as raised:
                    transport.evaluate("s", {})
                self.assertEqual(kind, raised.exception.kind)
                self.assertEqual(throttled, raised.exception.throttled)
                self.assertEqual(retry_after, raised.exception.retry_after_s)

    def test_timeout_and_network_failures(self) -> None:
        with self.assertRaises(AdvisorError) as raised:
            _transport([TimeoutError()], []).evaluate("s", {})
        self.assertEqual("timeout", raised.exception.kind)
        with self.assertRaises(AdvisorError) as raised:
            _transport([ConnectionRefusedError()], []).evaluate("s", {})
        self.assertEqual("network", raised.exception.kind)

    def test_reuses_connection_and_retries_once_when_it_went_stale(self) -> None:
        log: list[dict[str, object]] = []
        created: list[FakeConnection] = []
        script: list[object] = [_ok({}), ConnectionResetError(), _ok({})]
        transport = _transport(script, log, created)
        transport.evaluate("s", {})
        transport.evaluate("s", {})
        self.assertEqual(3, len(log))
        self.assertEqual(2, len(created))
        self.assertTrue(created[0].closed)

    def test_key_stays_out_of_repr_and_errors(self) -> None:
        transport = _transport([FakeResponse(401, b'{"detail": "bad key"}')], [])
        self.assertNotIn(FAKE_KEY, repr(transport))
        with self.assertRaises(AdvisorError) as raised:
            transport.evaluate("s", {})
        self.assertNotIn(FAKE_KEY, str(raised.exception))
        self.assertNotIn(FAKE_KEY, repr(raised.exception))

    def test_from_environment_needs_a_key(self) -> None:
        self.assertIsNone(JevTransport.from_environment({}))
        self.assertIsNone(JevTransport.from_environment({"TYPESAFE_API_KEY": "  "}))
        transport = JevTransport.from_environment(
            {"TYPESAFE_API_KEY": FAKE_KEY, "ROBOCODE_JEV_MODEL": "jev-latest", "ROBOCODE_JEV_TIMEOUT_MS": "900"}
        )
        self.assertIsNotNone(transport)
        self.assertEqual("jev-latest", transport.model)
        self.assertAlmostEqual(0.9, transport.timeout_s)


if __name__ == "__main__":
    unittest.main()
