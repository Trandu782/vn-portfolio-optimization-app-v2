"""The failover chain: order, failover, circuit breaker and all-down behaviour."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from support import FakeClock, FakeProvider, daily_bars, make_bar

from data.errors import AllProvidersFailedError, NetworkError
from data.fallback import FallbackProvider
from data.settings import DataSettings

TODAY = date(2024, 1, 8)
BARS = daily_bars(date(2024, 1, 2), 5)


def _settings() -> DataSettings:
    return DataSettings(
        database_url="sqlite://",
        provider_order="a,b,c",
        retry_attempts=1,
        circuit_breaker_failures=2,
        circuit_breaker_cooldown_seconds=60,
        stale_window_days=7,
        stale_tolerance_days=1,
    )


def _clock() -> datetime:
    return datetime(2024, 1, 8, tzinfo=UTC)


def _chain(
    providers: list[FakeProvider], clock: FakeClock | None = None
) -> FallbackProvider:
    return FallbackProvider(
        providers,
        settings=_settings(),
        order=[provider.id for provider in providers],
        clock=clock or _clock,
        sleeper=lambda _seconds: None,
        today_provider=lambda: TODAY,
    )


def test_first_healthy_provider_serves() -> None:
    result = _chain(
        [FakeProvider("a", bars=BARS), FakeProvider("b", bars=BARS)]
    ).get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    assert result.provider == "a"
    assert result.failovers == []


def test_disabling_first_provider_uses_second() -> None:
    a = FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True)
    b = FakeProvider("b", bars=BARS)
    result = _chain([a, b, FakeProvider("c", bars=BARS)]).get_daily_prices(
        "VNM", date(2024, 1, 2), TODAY
    )
    assert result.provider == "b"
    assert [event.provider for event in result.failovers] == ["a"]
    assert result.failovers[0].error_type == "network"


def test_disabling_first_two_providers_uses_third() -> None:
    a = FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True)
    b = FakeProvider("b", error=NetworkError("down", provider="b"), always_fail=True)
    c = FakeProvider("c", bars=BARS)
    result = _chain([a, b, c]).get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    assert result.provider == "c"
    assert [event.provider for event in result.failovers] == ["a", "b"]


def test_empty_response_triggers_failover() -> None:
    a = FakeProvider("a", bars=[])
    b = FakeProvider("b", bars=BARS)
    result = _chain([a, b]).get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    assert result.provider == "b"
    assert result.failovers[0].error_type == "empty"


def test_bad_schema_triggers_failover() -> None:
    a = FakeProvider("a", bars=[make_bar(date(2024, 1, 2), -5.0)])
    b = FakeProvider("b", bars=BARS)
    result = _chain([a, b]).get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    assert result.provider == "b"
    assert result.failovers[0].error_type == "schema"


def test_stale_data_triggers_failover() -> None:
    stale = FakeProvider("a", bars=daily_bars(date(2023, 12, 1), 3))
    fresh = FakeProvider("b", bars=BARS)
    result = _chain([stale, fresh]).get_daily_prices(
        "VNM", date(2023, 12, 1), TODAY
    )
    assert result.provider == "b"
    assert result.failovers[0].error_type == "stale"


def test_circuit_breaker_skips_provider_during_cooldown() -> None:
    failure = NetworkError("down", provider="a")
    a = FakeProvider("a", error=failure, always_fail=True)
    b = FakeProvider("b", bars=BARS)
    clock = FakeClock()
    chain = _chain([a, b], clock=clock)

    chain.get_daily_prices("VNM", date(2024, 1, 2), TODAY)  # a fails (1)
    chain.get_daily_prices("VNM", date(2024, 1, 2), TODAY)  # a fails (2) -> cooldown
    runtime = chain.runtime_for("a")
    assert runtime is not None
    assert runtime.cooldown_until is not None

    calls_before = a.calls
    chain.get_daily_prices("VNM", date(2024, 1, 2), TODAY)  # a skipped during cooldown
    assert a.calls == calls_before

    clock.advance(61)  # cooldown expires -> half-open trial
    chain.get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    assert a.calls > calls_before


def test_all_providers_down_raises() -> None:
    a = FakeProvider("a", error=NetworkError("a", provider="a"), always_fail=True)
    b = FakeProvider("b", error=NetworkError("b", provider="b"), always_fail=True)
    with pytest.raises(AllProvidersFailedError) as exc_info:
        _chain([a, b]).get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    assert len(exc_info.value.failures) == 2


def test_status_reports_health_and_last_error() -> None:
    a = FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True)
    b = FakeProvider("b", bars=BARS)
    chain = _chain([a, b])
    chain.get_daily_prices("VNM", date(2024, 1, 2), TODAY)
    statuses = {status.id: status for status in chain.statuses()}
    assert statuses["a"].healthy is False
    assert statuses["a"].last_error_type == "network"
    assert statuses["b"].healthy is True
