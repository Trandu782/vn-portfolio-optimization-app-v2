"""Unit tests for the pooled, thread-safe HttpxHttpClient."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

from data.http import HttpxHttpClient


def test_httpx_client_reuses_persistent_client_and_throttles_per_host() -> None:
    """Different hosts do not block each other's rps slot; same host does; one Client is reused."""
    now = 100.0
    lock = threading.Lock()
    sleeps: list[float] = []

    def fake_clock() -> float:
        with lock:
            return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        with lock:
            sleeps.append(seconds)
            now += seconds

    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    client = HttpxHttpClient(
        user_agent="test-agent/1.0",
        rate_limit_per_minute=100,
        requests_per_second=2.0,
        sleep=fake_sleep,
        clock=fake_clock,
        transport=httpx.MockTransport(handler),
    )
    underlying = client._client
    assert isinstance(underlying, httpx.Client)

    r1 = client.get("https://host-a.example/one")
    r2 = client.get("https://host-b.example/one")
    r3 = client.get("https://host-a.example/two")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
    assert len(seen_urls) == 3
    # host-a -> 0 sleep, host-b -> 0 sleep (independent host!), host-a #2 -> 0.5s (1 / 2.0 rps)
    assert len(sleeps) == 1
    assert sleeps[0] == 0.5
    assert client._client is underlying

    client.close()
    assert underlying.is_closed


def test_httpx_client_rate_limiter_is_thread_safe_under_concurrent_requests() -> None:
    """Concurrent threads against one host serialize slots cleanly without negative sleeps."""
    now = 0.0
    lock = threading.Lock()
    sleeps: list[float] = []

    def fake_clock() -> float:
        with lock:
            return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        with lock:
            sleeps.append(seconds)
            now += seconds

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    with (
        HttpxHttpClient(
            user_agent="test-agent/1.0",
            rate_limit_per_minute=100,
            requests_per_second=4.0,
            sleep=fake_sleep,
            clock=fake_clock,
            transport=httpx.MockTransport(handler),
        ) as client,
        ThreadPoolExecutor(max_workers=3) as pool,
    ):
        futures = [
            pool.submit(client.get, f"https://same-host.example/item/{idx}")
            for idx in range(6)
        ]
        responses = [future.result() for future in futures]

    assert all(resp.status_code == 200 for resp in responses)
    assert all(duration >= 0.0 for duration in sleeps)
    assert len(sleeps) >= 5
