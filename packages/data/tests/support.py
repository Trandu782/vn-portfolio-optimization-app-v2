"""Shared test helpers: a scriptable fake provider, fixtures and a fake clock."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from data.models import PriceBar, SymbolInfo

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a recorded JSON fixture by file name."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_bar(
    day: date, close: float, *, source: str = "fake", volume: int = 1000
) -> PriceBar:
    """Build a valid price bar for tests."""
    return PriceBar(
        date=day,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        adj_close=close,
        volume=volume,
        value=None,
        source=source,
    )


def daily_bars(
    start: date, count: int, *, base: float = 100.0, step: float = 1.0, source: str = "fake"
) -> list[PriceBar]:
    """Build ``count`` consecutive calendar-day bars starting at ``start``."""
    return [
        make_bar(start + timedelta(days=offset), base + step * offset, source=source)
        for offset in range(count)
    ]


class FakeProvider:
    """A provider that returns scripted bars or raises a scripted error."""

    def __init__(
        self,
        provider_id: str,
        *,
        bars: list[PriceBar] | None = None,
        error: Exception | None = None,
        always_fail: bool = False,
        fail_first: int = 0,
        returns_adjusted: bool = False,
        supports_indexes: bool = True,
    ) -> None:
        self.id = provider_id
        self.display_name = provider_id
        self.returns_adjusted_prices = returns_adjusted
        self.supports_indexes = supports_indexes
        self.unofficial = True
        self._bars = list(bars or [])
        self._error = error
        self._always_fail = always_fail
        self._fail_first = fail_first
        self.calls = 0
        self.constituents = ["VNM", "FPT"]

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self._error is not None and (self._always_fail or self.calls <= self._fail_first):
            raise self._error

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        self._maybe_fail()
        return [bar.model_copy(update={"source": self.id}) for bar in self._bars]

    def get_index_daily(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        self._maybe_fail()
        return [bar.model_copy(update={"source": self.id}) for bar in self._bars]

    def get_index_constituents(self, index_code: str) -> list[str]:
        self._maybe_fail()
        return list(self.constituents)

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        self._maybe_fail()
        return [SymbolInfo(code="VNM", exchange="HOSE", source=self.id)]


class FakeClock:
    """A controllable clock for circuit-breaker tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2024, 1, 8, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
