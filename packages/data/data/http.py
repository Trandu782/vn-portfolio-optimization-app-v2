"""Anonymous HTTP access with a normal User-Agent, rate limiting and retries.

``HttpClient`` is a tiny Protocol so providers never depend on ``httpx`` directly;
tests inject a recorded-fixture client and the full provider parsing path runs
unchanged. :class:`HttpxHttpClient` is the production adapter: it sends a normal
browser User-Agent, keeps a rolling per-minute request budget plus an optional
requests-per-second cap (the precompute path's throttle), retries transient
failures with backoff, backs off on HTTP 429, and cools down per host on HTTP 403.

Only ``GET`` is exposed: the data layer never mutates an upstream.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from data.errors import DataError

#: Headers that make requests look like a normal browser tab.
DEFAULT_ACCEPT = "application/json, text/plain, */*"


class HttpRequestError(DataError):
    """A request could not be completed after retries (network or timeout)."""

    def __init__(self, message: str, *, timeout: bool) -> None:
        super().__init__(message)
        self.timeout = timeout


class HttpResponse:
    """A minimal response object independent of the HTTP library."""

    def __init__(self, status_code: int, body: str, url: str) -> None:
        self.status_code = status_code
        self.body = body
        self.url = url

    @property
    def text(self) -> str:
        """Return the raw response body."""
        return self.body

    def json(self) -> Any:
        """Decode the body as JSON, raising ``ValueError`` on invalid JSON."""
        import json

        return json.loads(self.body)


class HttpClient(Protocol):
    """The two methods providers need from an HTTP transport (GET and POST)."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Perform a GET request and return the raw response."""

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Perform a POST request with a JSON body and return the raw response."""


class HttpxHttpClient:
    """Production ``HttpClient`` backed by ``httpx`` with connection pooling."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 15.0,
        rate_limit_per_minute: int = 20,
        requests_per_second: float | None = None,
        retry_attempts: int = 2,
        backoff_seconds: float = 0.5,
        rate_limit_retry_attempts: int = 5,
        rate_limit_backoff_seconds: float = 2.0,
        cooldown_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._limit = max(1, rate_limit_per_minute)
        self._requests_per_second = max(0.0, requests_per_second or 0.0)
        self._attempts = max(1, retry_attempts)
        self._backoff = backoff_seconds
        self._rate_limit_attempts = max(1, rate_limit_retry_attempts)
        self._rate_limit_backoff = rate_limit_backoff_seconds
        self._cooldown_seconds = cooldown_seconds
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._recent_by_host: dict[str, deque[float]] = {}
        self._last_request_by_host: dict[str, float] = {}
        self._host_cooldowns: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=10),
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying pooled ``httpx.Client``."""
        self._client.close()

    def __enter__(self) -> HttpxHttpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _respect_rate_limit(self, host: str) -> None:
        """Reserve the next per-host rate-limit slot and sleep outside the lock."""
        with self._lock:
            now = self._clock()
            recent = self._recent_by_host.setdefault(host, deque())
            while recent and now - recent[0] >= 60.0:
                recent.popleft()
            minute_slot = (
                recent[-self._limit] + 60.0 if len(recent) >= self._limit else now
            )
            rps_slot = now
            if self._requests_per_second > 0:
                last = self._last_request_by_host.get(host)
                if last is not None:
                    rps_slot = last + (1.0 / self._requests_per_second)
            scheduled_at = max(now, minute_slot, rps_slot)
            self._last_request_by_host[host] = scheduled_at
            recent.append(scheduled_at)
            wait = scheduled_at - now
        if wait > 0:
            self._sleep(wait)

    def _await_cooldown(self, url: str) -> None:
        """Wait out a per-host 403 cooldown before sending the next request."""
        host = urlparse(url).netloc
        with self._lock:
            until = self._host_cooldowns.get(host)
            if until is None:
                return
            wait = until - self._clock()
            if wait <= 0:
                self._host_cooldowns.pop(host, None)
                return
        self._sleep(wait)
        with self._lock:
            if self._host_cooldowns.get(host) == until:
                self._host_cooldowns.pop(host, None)

    def _set_cooldown(self, url: str) -> None:
        """Start a per-host cooldown after a 403 block."""
        if self._cooldown_seconds > 0:
            host = urlparse(url).netloc
            with self._lock:
                self._host_cooldowns[host] = self._clock() + self._cooldown_seconds

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """GET ``url`` with retries on timeouts, transport errors, 429 and 5xx."""
        return self._request("GET", url, params=params, headers=headers)

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """POST ``url`` with a JSON body, retrying like :meth:`get`."""
        return self._request("POST", url, json_body=json, headers=headers)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Send one request, with 429 backoff and a 403 host cooldown.

        Transport errors and 5xx use the general ``retry_attempts`` budget; 429 uses
        a separate, longer ``rate_limit_retry_attempts`` budget with exponential
        backoff. A 403 is never retried: it sets a per-host cooldown that
        ``_await_cooldown`` sleeps out before the next request to that host.
        """
        request_headers = {
            "User-Agent": self._user_agent,
            "Accept": DEFAULT_ACCEPT,
            **dict(headers or {}),
        }
        host = urlparse(url).netloc
        self._await_cooldown(url)
        general = 0
        rate_limited = 0
        while True:
            self._respect_rate_limit(host)
            try:
                response = self._client.request(
                    method,
                    url,
                    params=dict(params) if params else None,
                    json=json_body,
                    headers=request_headers,
                )
            except httpx.TimeoutException as exc:  # pragma: no cover - network only
                general += 1
                if general >= self._attempts:
                    raise HttpRequestError(f"timeout: {exc}", timeout=True) from exc
                self._sleep(self._backoff * (2 ** (general - 1)))
                continue
            except httpx.HTTPError as exc:  # pragma: no cover - network only
                general += 1
                if general >= self._attempts:
                    raise HttpRequestError(f"network error: {exc}", timeout=False) from exc
                self._sleep(self._backoff * (2 ** (general - 1)))
                continue
            if response.status_code == 403:
                self._set_cooldown(url)
                return HttpResponse(response.status_code, response.text, str(response.url))
            if response.status_code == 429:
                rate_limited += 1
                if rate_limited >= self._rate_limit_attempts:
                    return HttpResponse(response.status_code, response.text, str(response.url))
                self._sleep(self._rate_limit_backoff * (2 ** (rate_limited - 1)))
                continue
            if response.status_code >= 500:
                general += 1
                if general >= self._attempts:
                    return HttpResponse(response.status_code, response.text, str(response.url))
                self._sleep(self._backoff * (2 ** (general - 1)))
                continue
            return HttpResponse(response.status_code, response.text, str(response.url))


__all__ = [
    "DEFAULT_ACCEPT",
    "HttpClient",
    "HttpRequestError",
    "HttpResponse",
    "HttpxHttpClient",
]
