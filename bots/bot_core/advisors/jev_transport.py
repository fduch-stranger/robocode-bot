"""Jev System One transport over HTTPS, using only the standard library.

The API key comes from ``TYPESAFE_API_KEY``. It is sent only in the Authorization header and never
appears in reprs, exceptions, or telemetry. Each calling thread keeps one persistent connection, so
only the first request per thread pays for the TLS handshake.
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
MODEL_ENV = "ROBOCODE_JEV_MODEL"
TIMEOUT_ENV = "ROBOCODE_JEV_TIMEOUT_MS"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_TIMEOUT_MS = 1500
ENDPOINT_PATH = "/v1/systemone"
USER_AGENT = "robocode-bot-advisor/1"
THROTTLE_STATUSES = frozenset({429, 529})
MAX_RETRY_AFTER_SECONDS = 30.0
_STATUS_KINDS = {
    401: "auth",
    403: "forbidden",
    404: "not_found",
    422: "invalid_request",
    429: "rate_limited",
    529: "overloaded",
}


class AdvisorError(Exception):
    """A failed advisor call. ``kind`` is a short label that is safe to log."""

    def __init__(self, kind: str, *, status: int | None = None, retry_after_s: float | None = None) -> None:
        super().__init__(kind if status is None else f"{kind} (HTTP {status})")
        self.kind = kind
        self.status = status
        self.retry_after_s = retry_after_s

    @property
    def throttled(self) -> bool:
        return self.status in THROTTLE_STATUSES


@dataclass(frozen=True)
class TransportResponse:
    answers: dict[str, Any]
    model: str | None
    input_tokens: int | None


ConnectionFactory = Callable[[str, str, int | None, float, ssl.SSLContext | None], http.client.HTTPConnection]


def _default_connection(
    scheme: str,
    host: str,
    port: int | None,
    timeout_s: float,
    context: ssl.SSLContext | None,
) -> http.client.HTTPConnection:
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout_s, context=context)
    return http.client.HTTPConnection(host, port, timeout=timeout_s)


class JevTransport:
    """Posts System One requests to ``<base_url>/v1/systemone``."""

    name = "jev"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("the base URL must be an http or https URL")
        self._authorization = f"Bearer {api_key}"
        self._scheme = parts.scheme
        self._host = parts.hostname
        self._port = parts.port
        self._path = parts.path.rstrip("/") + ENDPOINT_PATH
        self.model = model
        self.timeout_s = max(0.05, timeout_ms / 1000.0)
        self._connection_factory = connection_factory or _default_connection
        self._ssl_context = ssl.create_default_context() if parts.scheme == "https" else None
        self._local = threading.local()

    def __repr__(self) -> str:
        return f"JevTransport(host={self._host!r}, model={self.model!r})"

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> JevTransport | None:
        """Build a transport from the environment, or return None when no key is set."""
        values = os.environ if env is None else env
        api_key = values.get(API_KEY_ENV, "").strip()
        if not api_key:
            return None
        return cls(
            api_key,
            base_url=values.get(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL,
            model=values.get(MODEL_ENV, "").strip() or DEFAULT_MODEL,
            timeout_ms=_int_value(values.get(TIMEOUT_ENV), DEFAULT_TIMEOUT_MS),
        )

    def evaluate(self, state: object, questions: Mapping[str, Mapping[str, Any]]) -> TransportResponse:
        body = json.dumps(
            {"state": state, "model": self.model, "questions": questions},
            separators=(",", ":"),
        ).encode("utf-8")
        status, raw, retry_after = self._post(body)
        if status != 200:
            raise AdvisorError(
                _STATUS_KINDS.get(status, "server_error" if status >= 500 else "http_error"),
                status=status,
                retry_after_s=_retry_after_seconds(retry_after),
            )
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            raise AdvisorError("parse") from None
        answers = payload.get("answers") if isinstance(payload, dict) else None
        if not isinstance(answers, dict):
            raise AdvisorError("parse")
        usage = payload.get("usage")
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        model = payload.get("model")
        return TransportResponse(
            answers=answers,
            model=model if isinstance(model, str) else None,
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        )

    def close(self) -> None:
        self._drop_connection()

    def _post(self, body: bytes) -> tuple[int, bytes, str | None]:
        headers = {
            "Authorization": self._authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        for attempt in range(2):
            reused = getattr(self._local, "connection", None) is not None
            connection = self._connection()
            try:
                connection.request("POST", self._path, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                if response.will_close:
                    self._drop_connection()
                return response.status, raw, response.getheader("Retry-After")
            except TimeoutError:
                self._drop_connection()
                raise AdvisorError("timeout") from None
            except ssl.SSLError:
                self._drop_connection()
                raise AdvisorError("ssl") from None
            except (http.client.HTTPException, OSError):
                self._drop_connection()
                if reused and attempt == 0:
                    # The server closed an idle keep-alive connection; retry once on a new one.
                    continue
                raise AdvisorError("network") from None
        raise AdvisorError("network")

    def _connection(self) -> http.client.HTTPConnection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connection_factory(
                self._scheme,
                self._host,
                self._port,
                self.timeout_s,
                self._ssl_context,
            )
            self._local.connection = connection
        return connection

    def _drop_connection(self) -> None:
        connection = getattr(self._local, "connection", None)
        self._local.connection = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _int_value(raw: str | None, default: int) -> int:
    try:
        return max(1, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def _retry_after_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return min(MAX_RETRY_AFTER_SECONDS, max(0.0, seconds))
