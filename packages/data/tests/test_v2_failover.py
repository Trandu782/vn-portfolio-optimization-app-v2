"""V2 failover runner: order, retry, 429/403, cache, rate limit and all-down."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from data.errors import AllProvidersFailedError, NetworkError, RateLimitError
from data.v2.config import V2DataSettings
from data.v2.errors import BlockedError, NoProvidersConfiguredError
from data.v2.interfaces import ProviderChains
from data.v2.runner import FailoverRunner
from data.v2.schemas import AdjustedOHLCV, SectorMap

START = date(2024, 1, 2)
END = date(2024, 1, 8)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2024, 1, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _bar() -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=START,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=1000,
        matched_volume=None,
        value=None,
        source="fake",
    )


class FakeOhlcv:
    def __init__(
        self, provider_id: str, *, error: Exception | None = None, fail_times: int = 0
    ) -> None:
        self.id = provider_id
        self.display_name = provider_id
        self.returns_adjusted = False
        self._error = error
        self._fail_times = fail_times
        self.calls = 0

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self._error is not None and (self._fail_times < 0 or self.calls <= self._fail_times):
            raise self._error

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        self._maybe_fail()
        return [_bar()]

    def get_index_ohlcv(
        self, index_code: str, start: date, end: date
    ) -> list[AdjustedOHLCV]:
        self._maybe_fail()
        return [_bar()]


class FakeSector:
    def __init__(self, provider_id: str, *, supports_bulk: bool) -> None:
        self.id = provider_id
        self.display_name = provider_id
        self.supports_bulk_sector_map = supports_bulk
        self.per_ticker: list[str] = []
        self.bulk_calls = 0

    def get_sector_map(self, ticker: str) -> SectorMap:
        self.per_ticker.append(ticker)
        return SectorMap(ticker=ticker, exchange="HOSE", source=self.id)

    def get_sector_map_all(self) -> list[SectorMap]:
        self.bulk_calls += 1
        return [SectorMap(ticker="VCB", exchange="HOSE", source=self.id)]


def _settings(**overrides: Any) -> V2DataSettings:
    base: dict[str, Any] = {
        "ohlcv_order": "a,b",
        "retry_attempts": 1,
        "retry_backoff_seconds": 0.0,
        "retry_jitter_seconds": 0.0,
        "cache_ttl_seconds": 0.0,
        "circuit_breaker_failures": 5,
        "ohlcv_rate_limit_per_minute": 1000,
        "sector_map_rate_limit_per_minute": 1000,
    }
    base.update(overrides)
    return V2DataSettings(**base)


def _runner(
    providers: list[FakeOhlcv] | None = None,
    *,
    settings: V2DataSettings | None = None,
    clock: FakeClock | None = None,
    sleeper: Any = None,
    monotonic: Any = None,
    sector: list[FakeSector] | None = None,
) -> FailoverRunner:
    return FailoverRunner(
        settings=settings or _settings(),
        chains=ProviderChains(ohlcv=providers or [], sector_map=sector or []),
        clock=clock or FakeClock(),
        sleeper=sleeper or (lambda _seconds: None),
        monotonic=monotonic or FakeMonotonic(),
        rng=random.Random(0),
    )


def test_primary_fails_secondary_serves() -> None:
    a = FakeOhlcv("a", error=NetworkError("down", provider="a"), fail_times=-1)
    b = FakeOhlcv("b")
    result = _runner([a, b]).ohlcv("VCB", START, END)
    assert result.provider == "b"
    assert result.from_cache is False
    assert a.calls == 1


def test_all_fail_raises_clear_error() -> None:
    a = FakeOhlcv("a", error=NetworkError("a", provider="a"), fail_times=-1)
    b = FakeOhlcv("b", error=NetworkError("b", provider="b"), fail_times=-1)
    with pytest.raises(AllProvidersFailedError) as info:
        _runner([a, b]).ohlcv("VCB", START, END)
    assert len(info.value.failures) == 2


def test_disabling_primary_in_config_still_returns_data() -> None:
    a = FakeOhlcv("a")
    b = FakeOhlcv("b")
    settings = _settings(ohlcv_order="b")
    ordered = {provider.id: provider for provider in (a, b)}
    chain = [ordered[pid] for pid in settings.chain("ohlcv") if pid in ordered]
    result = _runner(chain, settings=settings).ohlcv("VCB", START, END)
    assert result.provider == "b"
    assert a.calls == 0


def test_empty_chain_raises() -> None:
    with pytest.raises(NoProvidersConfiguredError):
        _runner([]).ohlcv("VCB", START, END)


def test_cache_hit_avoids_recall() -> None:
    a = FakeOhlcv("a")
    settings = _settings(cache_ttl_seconds=60.0)
    runner = _runner([a], settings=settings)
    first = runner.ohlcv("VCB", START, END)
    second = runner.ohlcv("VCB", START, END)
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.provider == "a"
    assert a.calls == 1


def test_rate_limit_error_retries_then_succeeds() -> None:
    a = FakeOhlcv("a", error=RateLimitError("429", provider="a"), fail_times=1)
    sleeps: list[float] = []
    settings = _settings(retry_attempts=2, retry_backoff_seconds=0.1)
    result = _runner([a], settings=settings, sleeper=sleeps.append).ohlcv("VCB", START, END)
    assert result.provider == "a"
    assert a.calls == 2
    assert sleeps and sleeps[0] >= 0.1


def test_403_is_blocked_no_retry_and_cools_down() -> None:
    a = FakeOhlcv("a", error=BlockedError("403", provider="a"), fail_times=-1)
    b = FakeOhlcv("b")
    runner = _runner([a, b], settings=_settings(retry_attempts=3))
    result = runner.ohlcv("VCB", START, END)
    assert result.provider == "b"
    assert a.calls == 1  # 403 is not retried
    assert runner.health("ohlcv")["a"].cooldown_until is not None
    runner.ohlcv("VCB", START, END)
    assert a.calls == 1  # still skipped while cooling down


def test_health_tracks_failures_and_success() -> None:
    a = FakeOhlcv("a", error=NetworkError("down", provider="a"), fail_times=1)
    runner = _runner([a], settings=_settings(retry_attempts=1))
    with pytest.raises(AllProvidersFailedError):
        runner.ohlcv("VCB", START, END)
    health = runner.health("ohlcv")["a"]
    assert health.consecutive_failures == 1
    assert health.last_error_type == "network"
    runner.ohlcv("VCB", date(2024, 1, 3), END)
    assert runner.health("ohlcv")["a"].consecutive_failures == 0


def test_per_data_type_rate_limit_enforced() -> None:
    a = FakeOhlcv("a")
    sleeps: list[float] = []
    settings = _settings(ohlcv_rate_limit_per_minute=2)
    runner = _runner([a], settings=settings, sleeper=sleeps.append)
    runner.ohlcv("VCB", START, END)
    runner.ohlcv("FPT", START, END)
    runner.ohlcv("HPG", START, END)
    assert any(seconds >= 60.0 for seconds in sleeps)


def test_sector_map_all_uses_per_ticker_fallback() -> None:
    provider = FakeSector("vci", supports_bulk=False)
    result = _runner(sector=[provider]).sector_map_all(["VCB", "FPT"])
    assert provider.bulk_calls == 0
    assert provider.per_ticker == ["VCB", "FPT"]
    assert {sector.ticker for sector in result.value} == {"VCB", "FPT"}


def test_sector_map_all_prefers_bulk() -> None:
    provider = FakeSector("vci", supports_bulk=True)
    result = _runner(sector=[provider]).sector_map_all(["VCB", "FPT"])
    assert provider.bulk_calls == 1
    assert provider.per_ticker == []
    assert len(result.value) == 1
