"""Non-blocking advisor client: the bot submits requests during its turn and drains answers later.

Worker threads do the network I/O. ``submit`` never blocks: it applies a client-side rate limit,
refuses requests while the service asks us to back off, and drops the oldest queued request when
the queue is full. Every failure becomes an ``AdvisorResult`` with an error label, so the bot always
falls back to its own decision.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from bot_core.advisors.jev_transport import AdvisorError, TransportResponse

DEFAULT_THROTTLE_PAUSE_S = 1.0
MAX_PENDING_RESULTS = 256

SUBMIT_QUEUED = "queued"
SUBMIT_RATE_LIMITED = "rate_limited"
SUBMIT_BACKOFF = "backoff"
SUBMIT_CLOSED = "closed"


class AdvisorTransport(Protocol):
    name: str

    def evaluate(self, state: object, questions: Mapping[str, Mapping[str, Any]]) -> TransportResponse: ...


@dataclass(frozen=True)
class AdvisorRequest:
    kind: str
    key: object
    request_turn: int
    state: object
    questions: dict[str, dict[str, Any]]
    # Bot-side data kept with the request for logging and evaluation; never sent.
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisorResult:
    request: AdvisorRequest
    answers: dict[str, Any] | None
    error: str | None
    status: int | None
    latency_ms: float
    model: str | None = None
    input_tokens: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.answers is not None


class AdvisorClient:
    def __init__(
        self,
        transport: AdvisorTransport,
        *,
        max_queue: int = 2,
        workers: int = 2,
        max_rps: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        start: bool = True,
    ) -> None:
        self.transport = transport
        self._max_queue = max(1, max_queue)
        self._max_rps = max(0.1, max_rps)
        self._clock = clock
        self._condition = threading.Condition()
        self._queue: deque[AdvisorRequest] = deque()
        self._results: deque[AdvisorResult] = deque(maxlen=MAX_PENDING_RESULTS)
        self._tokens = self._max_rps
        self._tokens_at = clock()
        self._pause_until = 0.0
        self._closed = False
        self._counts = {
            "submitted": 0,
            "queued": 0,
            "sent": 0,
            "ok": 0,
            "errors": 0,
            "throttled": 0,
            "dropped_queue_full": 0,
            "rejected_rate": 0,
            "rejected_backoff": 0,
        }
        self._threads = [
            threading.Thread(target=self._work, name=f"advisor-worker-{index}", daemon=True)
            for index in range(max(1, workers))
        ]
        if start:
            for thread in self._threads:
                thread.start()

    def submit(self, request: AdvisorRequest) -> str:
        with self._condition:
            self._counts["submitted"] += 1
            if self._closed:
                return SUBMIT_CLOSED
            now = self._clock()
            if now < self._pause_until:
                self._counts["rejected_backoff"] += 1
                return SUBMIT_BACKOFF
            self._refill(now)
            if self._tokens < 1.0:
                self._counts["rejected_rate"] += 1
                return SUBMIT_RATE_LIMITED
            self._tokens -= 1.0
            if len(self._queue) >= self._max_queue:
                self._queue.popleft()
                self._counts["dropped_queue_full"] += 1
            self._queue.append(request)
            self._counts["queued"] += 1
            self._condition.notify()
            return SUBMIT_QUEUED

    def drain(self) -> list[AdvisorResult]:
        with self._condition:
            results = list(self._results)
            self._results.clear()
        return results

    def stats(self) -> dict[str, int]:
        with self._condition:
            return dict(self._counts, pending=len(self._queue))

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._condition.notify_all()
        close = getattr(self.transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def process_next(self) -> bool:
        """Handle one queued request on the calling thread; for tests built with ``start=False``."""
        with self._condition:
            if not self._queue:
                return False
            request = self._queue.popleft()
        self._handle(request)
        return True

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._tokens_at)
        self._tokens = min(self._max_rps, self._tokens + elapsed * self._max_rps)
        self._tokens_at = now

    def _work(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                request = self._queue.popleft()
                wait_s = self._pause_until - self._clock()
            if wait_s > 0:
                time.sleep(wait_s)
            self._handle(request)

    def _handle(self, request: AdvisorRequest) -> None:
        with self._condition:
            self._counts["sent"] += 1
        started = time.perf_counter()
        try:
            response = self.transport.evaluate(request.state, request.questions)
        except AdvisorError as error:
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._finish(AdvisorResult(request, None, error.kind, error.status, latency_ms))
            if error.throttled:
                pause = error.retry_after_s if error.retry_after_s is not None else DEFAULT_THROTTLE_PAUSE_S
                with self._condition:
                    self._counts["throttled"] += 1
                    self._pause_until = max(self._pause_until, self._clock() + pause)
            return
        except Exception as error:  # noqa: BLE001 - a worker must never die; the bot falls back.
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._finish(AdvisorResult(request, None, f"exception:{type(error).__name__}", None, latency_ms))
            return
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._finish(
            AdvisorResult(
                request,
                response.answers,
                None,
                None,
                latency_ms,
                response.model,
                response.input_tokens,
            )
        )

    def _finish(self, result: AdvisorResult) -> None:
        with self._condition:
            self._counts["ok" if result.ok else "errors"] += 1
            if not self._closed:
                self._results.append(result)
