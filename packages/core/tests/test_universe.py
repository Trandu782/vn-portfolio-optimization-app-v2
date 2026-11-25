"""Unit tests for universe selection: filters, the registry and build_universe."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from core.registry import Registry
from core.universe import (
    DailyBar,
    FilterSpec,
    SymbolSeries,
    UniverseFilter,
    build_filter,
    build_filters,
    build_universe,
    traded_value,
    universe_filters,
)

START = date(2023, 1, 2)


def _bars(
    count: int,
    *,
    base: float = 50.0,
    volume: int = 100_000,
    value: float | None = None,
) -> tuple[DailyBar, ...]:
    """Return ``count`` consecutive daily bars starting at :data:`START`."""
    return tuple(
        DailyBar(
            date=START + timedelta(days=offset),
            close=base + offset,
            adj_close=base + offset,
            volume=volume,
            value=value,
        )
        for offset in range(count)
    )


def _series(
    code: str,
    exchange: str = "HOSE",
    count: int = 12,
    *,
    base: float = 50.0,
    volume: int = 100_000,
    value: float | None = None,
    suspended: bool = False,
    delisted: bool = False,
    stale: bool = False,
) -> SymbolSeries:
    """Build a candidate symbol with ``count`` in-range bars."""
    return SymbolSeries(
        code=code,
        exchange=exchange,
        bars=_bars(count, base=base, volume=volume, value=value),
        suspended=suspended,
        delisted=delisted,
        stale=stale,
    )


def _window(days: int = 60) -> tuple[date, date]:
    return START, START + timedelta(days=days)


def test_builtin_filters_are_registered_with_parameter_schemas() -> None:
    descriptions = {info.id: info for info in universe_filters.describe()}
    assert {
        "exchange",
        "min_adv",
        "exclude_suspended",
        "exclude_stale_prices",
        "min_history",
    } <= set(descriptions)

    min_adv_schema = descriptions["min_adv"].parameter_schema
    assert min_adv_schema is not None
    assert min_adv_schema["properties"]["min_value_vnd"]["default"] == 1_000_000_000.0


def test_a_new_filter_is_one_file_and_one_registration() -> None:
    """A filter can be added by registering a class; build_universe needs no change."""

    class BlockCodeParams(BaseModel):
        blocked: str = "BAD"

    registry: Registry[UniverseFilter] = Registry()

    @registry.register(
        id="block",
        name="Block code",
        description="Drop one specific code.",
        parameter_schema=BlockCodeParams,
    )
    class BlockCode:
        id = "block"

        def __init__(self, params: dict[str, object] | None = None) -> None:
            resolved = BlockCodeParams(**(params or {}))
            self._blocked = resolved.blocked.upper()

        def apply(self, candidate: SymbolSeries) -> str | None:
            if candidate.code == self._blocked:
                return f"{candidate.code} is blocked"
            return None

    assert registry.list() == ["block"]

    filters = build_filters([FilterSpec("block", {"blocked": "BAD"})], registry=registry)
    result = build_universe([_series("GOOD"), _series("BAD")], filters, *_window())

    assert result.symbols == ("GOOD",)
    [dropped] = result.dropped
    assert dropped.code == "BAD"
    assert dropped.filter_id == "block"
    assert "blocked" in dropped.reason


def test_build_universe_aligns_price_and_returns_matrices() -> None:
    a = _series("AAA", count=5, base=10.0)
    b = _series("BBB", count=5, base=20.0)

    result = build_universe([a, b], [], *_window())

    assert result.symbols == ("AAA", "BBB")
    assert len(result.dates) == 5
    assert result.price_matrix.shape == (5, 2)
    assert result.returns_matrix.shape == (4, 2)
    assert result.price_matrix[0, 0] == pytest.approx(10.0)
    assert result.price_matrix[0, 1] == pytest.approx(20.0)
    assert result.returns_matrix[0, 0] == pytest.approx(0.1)
    assert result.returns_dates == result.dates[1:]


def test_exchange_filter_drops_other_board_with_reason() -> None:
    filters = [build_filter("exchange", {"exchange": "HOSE"})]

    result = build_universe(
        [_series("AAA", "HOSE"), _series("BBB", "HNX")], filters, *_window()
    )

    assert result.symbols == ("AAA",)
    [dropped] = result.dropped
    assert dropped.code == "BBB"
    assert dropped.filter_id == "exchange"
    assert "HNX" in dropped.reason


def test_min_history_filter_drops_short_series_with_reason() -> None:
    filters = [build_filter("min_history", {"min_sessions": 10})]

    result = build_universe(
        [_series("LONG", count=10), _series("SHORT", count=3)], filters, *_window()
    )

    assert result.symbols == ("LONG",)
    [dropped] = result.dropped
    assert dropped.code == "SHORT"
    assert dropped.filter_id == "min_history"
    assert "sessions" in dropped.reason


def test_min_adv_filter_drops_illiquid_ticker_with_reason() -> None:
    filters = [build_filter("min_adv", {"min_value_vnd": 1_000_000_000, "sessions": 5})]
    liquid = _series("LIQ", count=5, value=2_000_000_000)
    illiquid = _series("ILL", count=5, value=10_000_000)

    result = build_universe([liquid, illiquid], filters, *_window())

    assert result.symbols == ("LIQ",)
    [dropped] = result.dropped
    assert dropped.code == "ILL"
    assert dropped.filter_id == "min_adv"
    assert "average daily traded value" in dropped.reason
    assert result.quality_flags["LIQ"].illiquid is False


def test_exclude_suspended_filter_drops_flagged_symbols() -> None:
    filters = [build_filter("exclude_suspended")]

    result = build_universe(
        [_series("OK"), _series("SUS", suspended=True), _series("DEL", delisted=True)],
        filters,
        *_window(),
    )

    assert result.symbols == ("OK",)
    reasons = {dropped.code: dropped.reason for dropped in result.dropped}
    assert reasons["SUS"] == "suspended"
    assert reasons["DEL"] == "delisted"


def test_exclude_stale_prices_filter_drops_stale_with_its_own_reason() -> None:
    """A trailing bar is dropped as stale data — never mislabelled as suspended."""
    filters = [build_filter("exclude_stale_prices")]

    result = build_universe(
        [_series("CURRENT"), _series("STALE", stale=True)], filters, *_window()
    )

    assert result.symbols == ("CURRENT",)
    [dropped] = result.dropped
    assert dropped.code == "STALE"
    assert dropped.filter_id == "exclude_stale_prices"
    assert dropped.reason == "stale_price_data"


def test_a_stale_symbol_is_flagged_but_not_suspended() -> None:
    """The quality flags keep suspension and staleness separate."""
    result = build_universe(
        [_series("STALE", stale=True), _series("SUS", suspended=True)], [], *_window()
    )

    assert result.quality_flags["STALE"].stale is True
    assert result.quality_flags["STALE"].suspended is False
    assert result.quality_flags["SUS"].suspended is True
    assert result.quality_flags["SUS"].stale is False


def test_symbol_without_data_in_range_is_dropped_with_reason() -> None:
    outside = SymbolSeries(code="NONE", exchange="HOSE", bars=_bars(3))

    start = START + timedelta(days=100)
    result = build_universe([outside], [], start, start + timedelta(days=100))

    [dropped] = result.dropped
    assert dropped.code == "NONE"
    assert dropped.filter_id is None
    assert "no price data" in dropped.reason


def test_missing_days_are_flagged_after_alignment() -> None:
    full = _series("FULL", count=5)
    gappy = SymbolSeries(
        "GAPPY", "HOSE", (full.bars[0], full.bars[1], full.bars[3], full.bars[4])
    )

    result = build_universe([full, gappy], [], *_window())

    assert result.symbols == ("FULL", "GAPPY")
    assert result.quality_flags["FULL"].missing_data is False
    assert result.quality_flags["GAPPY"].missing_data is True


def test_every_dropped_ticker_carries_a_reason() -> None:
    filters = [
        build_filter("exchange", {"exchange": "HOSE"}),
        build_filter("min_history", {"min_sessions": 10}),
    ]

    result = build_universe(
        [_series("HNX1", "HNX"), _series("SHORT", count=2)], filters, *_window()
    )

    assert result.symbols == ()
    assert len(result.dropped) == 2
    assert all(dropped.reason.strip() for dropped in result.dropped)


def test_empty_universe_returns_empty_matrices() -> None:
    result = build_universe([], [], START, START + timedelta(days=10))

    assert result.symbols == ()
    assert result.price_matrix.shape == (0, 0)
    assert result.returns_matrix.shape == (0, 0)
    assert result.dates == ()


def test_adv_falls_back_to_close_times_volume() -> None:
    without_value = DailyBar(date=START, close=50.0, adj_close=50.0, volume=1000, value=None)
    with_value = DailyBar(date=START, close=50.0, adj_close=50.0, volume=1000, value=1_000_000.0)

    assert traded_value(without_value) == pytest.approx(50_000.0)
    assert traded_value(with_value) == pytest.approx(1_000_000.0)


def test_reversed_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="start must not be after end"):
        build_universe([], [], date(2024, 1, 2), date(2024, 1, 1))


def test_unknown_filter_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        build_filter("does-not-exist")


def test_filter_rejects_invalid_parameters() -> None:
    with pytest.raises(ValidationError):
        build_filter("min_adv", {"min_value_vnd": -1})

