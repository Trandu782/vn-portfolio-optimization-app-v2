"""API security middleware: body size caps, per-IP rate limiting, and security headers."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Maximum accepted request payload size (512 KB).
MAX_REQUEST_BODY_BYTES = 512 * 1024

#: Rate-limit windows (requests per 60 seconds).
GENERAL_RATE_LIMIT = 120
COMPUTE_RATE_LIMIT = 20
AUTH_RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 60.0

_COMPUTE_PATHS = frozenset(
    {
        "/api/v1/optimize/frontier",
        "/api/v1/optimize",
        "/api/v1/risk",
        "/api/v1/risk/compare",
        "/api/v1/v2/analytics",
    }
)
_AUTH_PATHS = frozenset(
    {
        "/api/v1/data/refresh",
        "/api/v1/data/probe",
        "/api/v1/data/backfill",
    }
)
_NO_STORE_PATHS = _AUTH_PATHS

_BASE_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class _BodyTooLargeError(Exception):
    """Internal sentinel raised when a streamed request body exceeds the byte cap."""


def _header_value(scope: Scope, name: bytes) -> str | None:
    target = name.lower()
    for raw_name, raw_value in scope.get("headers", ()):
        if raw_name.lower() == target and isinstance(raw_value, bytes):
            return raw_value.decode("latin-1")
    return None


def extract_client_ip(scope: Scope) -> str:
    """Return the client IP, preferring the rightmost proxy entry in X-Forwarded-For."""
    forwarded = _header_value(scope, b"x-forwarded-for")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1]
    real_ip = _header_value(scope, b"x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    client = scope.get("client")
    if isinstance(client, tuple) and client and isinstance(client[0], str):
        return client[0]
    return "unknown"


def _rate_bucket_for_path(path: str) -> tuple[str, int]:
    if path in _AUTH_PATHS:
        return ("auth", AUTH_RATE_LIMIT)
    if path in _COMPUTE_PATHS:
        return ("compute", COMPUTE_RATE_LIMIT)
    return ("general", GENERAL_RATE_LIMIT)


class SlidingWindowRateLimiter:
    """Thread-safe, memory-bounded in-memory sliding-window rate limiter."""

    def __init__(
        self,
        *,
        window_seconds: float = RATE_WINDOW_SECONDS,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def allow(self, bucket: str, client_ip: str, limit: int) -> tuple[bool, int]:
        """Record one hit if under ``limit``; return ``(allowed, retry_after_seconds)``."""
        now = self._clock()
        cutoff = now - self._window
        key = (bucket, client_ip)
        with self._lock:
            if len(self._hits) >= self._max_keys and key not in self._hits:
                self._prune_expired_locked(cutoff)
                if len(self._hits) >= self._max_keys:
                    oldest_key = next(iter(self._hits))
                    self._hits.pop(oldest_key, None)
            timestamps = self._hits.setdefault(key, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= limit:
                retry_after = max(1, math.ceil(self._window - (now - timestamps[0])))
                return False, retry_after
            timestamps.append(now)
            return True, 0

    def _prune_expired_locked(self, cutoff: float) -> None:
        stale = [
            key
            for key, timestamps in self._hits.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for key in stale:
            self._hits.pop(key, None)


async def _send_json_error(
    send: Send,
    status_code: int,
    detail: str,
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        *_BASE_SECURITY_HEADERS,
        *extra_headers,
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Attach standard security headers and ``Cache-Control: no-store`` on errors/admin routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        force_no_store_path = path in _NO_STORE_PATHS

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                status = int(message.get("status", 200))
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers", ()))
                existing_names = {name.lower() for name, _ in raw_headers}
                for name, value in _BASE_SECURITY_HEADERS:
                    if name not in existing_names:
                        raw_headers.append((name, value))
                if force_no_store_path or status >= 400:
                    raw_headers = [
                        (name, value)
                        for name, value in raw_headers
                        if name.lower() != b"cache-control"
                    ]
                    raw_headers.append((b"cache-control", b"no-store"))
                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """Per-IP sliding-window rate limiter with route-tier budgets."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool = True,
        limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self.app = app
        self._default_enabled = enabled
        self._limiter = limiter or SlidingWindowRateLimiter()

    def _is_enabled(self) -> bool:
        override = os.environ.get("VNOPT_RATE_LIMIT_ENABLED")
        if override is not None:
            return override.strip().lower() not in {"0", "false", "no", "off"}
        return self._default_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._is_enabled():
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        bucket, limit = _rate_bucket_for_path(path)
        client_ip = extract_client_ip(scope)
        allowed, retry_after = self._limiter.allow(bucket, client_ip, limit)
        if not allowed:
            await _send_json_error(
                send,
                429,
                "Rate limit exceeded. Try again later.",
                extra_headers=((b"retry-after", str(retry_after).encode("ascii")),),
            )
            return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Reject HTTP request payloads exceeding ``max_bytes`` with HTTP 413."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_length = _header_value(scope, b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                await _send_json_error(send, 400, "Invalid Content-Length header")
                return
            if content_length > self._max_bytes:
                await _send_json_error(send, 413, "Request body too large")
                return

        total_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal total_bytes
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                if isinstance(chunk, (bytes, bytearray)):
                    total_bytes += len(chunk)
                if total_bytes > self._max_bytes:
                    raise _BodyTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not response_started:
                await _send_json_error(send, 413, "Request body too large")


__all__ = [
    "AUTH_RATE_LIMIT",
    "COMPUTE_RATE_LIMIT",
    "GENERAL_RATE_LIMIT",
    "MAX_REQUEST_BODY_BYTES",
    "BodySizeLimitMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "SlidingWindowRateLimiter",
    "extract_client_ip",
]
