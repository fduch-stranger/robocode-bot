import threading
import time
import unittest

from bot_core.advisors.client import (
    SUBMIT_BACKOFF,
    SUBMIT_QUEUED,
    SUBMIT_RATE_LIMITED,
    AdvisorClient,
    AdvisorRequest,
)
from bot_core.advisors.jev_transport import AdvisorError, TransportResponse
from bot_core.advisors.stub_transport import StubTransport


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class ScriptedTransport:
    name = "scripted"

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def evaluate(self, state, questions) -> TransportResponse:
        self.calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else TransportResponse({"q": {"type": "choice"}}, "m", 1)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BlockingTransport:
    name = "blocking"

    def __init__(self) -> None:
        self.release = threading.Event()

    def evaluate(self, state, questions) -> TransportResponse:
        self.release.wait(5.0)
        return TransportResponse({}, "m", 0)


def _request(key: str, turn: int = 1) -> AdvisorRequest:
    return AdvisorRequest("surf", key, turn, {"s": 1}, {"q": {"type": "choice", "criteria": {"a": None}}})


class AdvisorClientTest(unittest.TestCase):
    def test_submit_never_blocks_on_a_slow_transport(self) -> None:
        transport = BlockingTransport()
        client = AdvisorClient(transport, max_queue=2, workers=1, max_rps=100.0)
        try:
            started = time.perf_counter()
            for index in range(20):
                client.submit(_request(f"k{index}"))
            elapsed = time.perf_counter() - started
        finally:
            transport.release.set()
            client.close()
        self.assertLess(elapsed, 0.05)
        self.assertGreater(client.stats()["dropped_queue_full"], 0)

    def test_full_queue_drops_the_oldest_request(self) -> None:
        transport = ScriptedTransport()
        client = AdvisorClient(transport, max_queue=2, max_rps=100.0, start=False)
        for key in ("a", "b", "c"):
            self.assertEqual(SUBMIT_QUEUED, client.submit(_request(key)))
        while client.process_next():
            pass
        self.assertEqual(["b", "c"], [result.request.key for result in client.drain()])
        self.assertEqual(1, client.stats()["dropped_queue_full"])

    def test_rate_limit_refills_over_time(self) -> None:
        clock = FakeClock()
        client = AdvisorClient(ScriptedTransport(), max_queue=10, max_rps=2.0, clock=clock, start=False)
        self.assertEqual(SUBMIT_QUEUED, client.submit(_request("a")))
        self.assertEqual(SUBMIT_QUEUED, client.submit(_request("b")))
        self.assertEqual(SUBMIT_RATE_LIMITED, client.submit(_request("c")))
        clock.now += 0.5
        self.assertEqual(SUBMIT_QUEUED, client.submit(_request("d")))
        self.assertEqual(1, client.stats()["rejected_rate"])

    def test_errors_become_results_and_never_raise(self) -> None:
        transport = ScriptedTransport(AdvisorError("timeout"), RuntimeError("boom"))
        client = AdvisorClient(transport, max_rps=100.0, start=False)
        client.submit(_request("a"))
        client.submit(_request("b"))
        while client.process_next():
            pass
        results = client.drain()
        self.assertEqual(["timeout", "exception:RuntimeError"], [result.error for result in results])
        self.assertFalse(any(result.ok for result in results))
        self.assertEqual(2, client.stats()["errors"])

    def test_throttling_pauses_new_submissions(self) -> None:
        clock = FakeClock()
        transport = ScriptedTransport(AdvisorError("rate_limited", status=429, retry_after_s=2.0))
        client = AdvisorClient(transport, max_rps=100.0, clock=clock, start=False)
        client.submit(_request("a"))
        client.process_next()
        self.assertEqual(SUBMIT_BACKOFF, client.submit(_request("b")))
        clock.now += 2.5
        self.assertEqual(SUBMIT_QUEUED, client.submit(_request("c")))
        self.assertEqual(1, client.stats()["throttled"])

    def test_worker_threads_deliver_stub_answers(self) -> None:
        client = AdvisorClient(StubTransport(mode="fixed", fixed_choices={"q": "a"}), max_rps=100.0)
        try:
            client.submit(_request("a"))
            deadline = time.monotonic() + 2.0
            results = []
            while not results and time.monotonic() < deadline:
                results = client.drain()
                time.sleep(0.005)
        finally:
            client.close()
        self.assertEqual(1, len(results))
        self.assertEqual("a", results[0].answers["q"]["choice"])


if __name__ == "__main__":
    unittest.main()
