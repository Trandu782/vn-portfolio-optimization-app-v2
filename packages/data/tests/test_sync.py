"""Incremental sync, idempotency, source-change consistency and batching."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker
from support import FakeProvider, daily_bars

from data.benchmarks import BENCHMARK_BY_CODE
from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.db.repositories import SqlIndexRepository, SqlPriceRepository
from data.errors import NetworkError
from data.fallback import FallbackProvider
from data.models import PriceBar
from data.service import DataService
from data.settings import DataSettings
from data.sync import SyncService

TODAY = date(2024, 1, 8)


def _clock() -> datetime:
    return datetime(2024, 1, 8, tzinfo=UTC)


def _settings() -> DataSettings:
    return DataSettings(
        database_url="sqlite://",
        provider_order="a,b",
        retry_attempts=1,
        stale_tolerance_days=1,
        on_demand_history_days=365,
        circuit_breaker_failures=5,
    )


@pytest.fixture
def factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine_for(f"sqlite:///{tmp_path / 'sync.db'}")
    create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _service(
    factory: sessionmaker[Session], providers: list[FakeProvider]
) -> SyncService:
    settings = _settings()
    fallback = FallbackProvider(
        providers,
        settings=settings,
        order=[provider.id for provider in providers],
        clock=_clock,
        sleeper=lambda _seconds: None,
        today_provider=lambda: TODAY,
    )
    return SyncService(
        session_factory=factory,
        fallback=fallback,
        settings=settings,
        today_provider=lambda: TODAY,
    )


def test_sync_symbol_is_incremental_and_idempotent(
    factory: sessionmaker[Session],
) -> None:
    service = _service(factory, [FakeProvider("a", bars=daily_bars(date(2024, 1, 2), 5))])
    first = service.sync_symbol("VNM")
    assert first.ok and first.status == "updated" and first.rows == 5
    second = service.sync_symbol("VNM")
    assert second.ok
    with session_scope(factory) as session:
        prices = SqlPriceRepository(session)
        assert prices.count("VNM") == 5
        assert prices.source_of_latest("VNM") == "a"


def test_all_providers_down_returns_queued(factory: sessionmaker[Session]) -> None:
    a = FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True)
    service = _service(factory, [a])
    result = service.sync_symbol("VNM")
    assert not result.ok
    assert result.status == "queued"
    with session_scope(factory) as session:
        assert SqlPriceRepository(session).count("VNM") == 0


def test_source_change_with_mismatch_replaces_history(
    factory: sessionmaker[Session],
) -> None:
    first = _service(factory, [FakeProvider("a", bars=daily_bars(date(2024, 1, 2), 5, base=100.0))])
    assert first.sync_symbol("VNM").status == "updated"

    second = _service(
        factory,
        [
            FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True),
            FakeProvider("b", bars=daily_bars(date(2024, 1, 2), 5, base=200.0)),
        ],
    )
    result = second.sync_symbol("VNM")
    assert result.status == "replaced"
    assert result.provider == "b"
    with session_scope(factory) as session:
        prices = SqlPriceRepository(session)
        assert prices.source_of_latest("VNM") == "b"
        rows = prices.get_range("VNM", date(2024, 1, 1), date(2024, 1, 10))
        assert rows[0].close == 200.0


def test_source_change_within_tolerance_does_not_replace(
    factory: sessionmaker[Session],
) -> None:
    first = _service(factory, [FakeProvider("a", bars=daily_bars(date(2024, 1, 2), 5, base=100.0))])
    first.sync_symbol("VNM")
    second = _service(
        factory,
        [
            FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True),
            FakeProvider("b", bars=daily_bars(date(2024, 1, 2), 5, base=100.0)),
        ],
    )
    result = second.sync_symbol("VNM")
    assert result.status == "updated"
    with session_scope(factory) as session:
        assert SqlPriceRepository(session).count("VNM") == 5


def test_sync_benchmarks_stores_index_rows(factory: sessionmaker[Session]) -> None:
    service = _service(
        factory,
        [FakeProvider("a", bars=daily_bars(date(2024, 1, 2), 5, base=1000.0))],
    )
    results = service.sync_benchmarks()
    assert len(results) == 4
    assert all(result.ok for result in results)
    with session_scope(factory) as session:
        indices = SqlIndexRepository(session)
        assert indices.count("VNINDEX") == 5


def test_refresh_batch_resumes_with_cursor(factory: sessionmaker[Session]) -> None:
    service = _service(
        factory,
        [FakeProvider("a", bars=daily_bars(date(2024, 1, 2), 5, base=1000.0))],
    )
    first = service.refresh_batch(limit=2)
    assert not first.done
    assert first.processed == 2
    assert first.remaining == 2
    assert first.cursor == 2

    second = service.refresh_batch(cursor=first.cursor, limit=2)
    assert second.done
    assert second.remaining == 0


class _RangeProvider(FakeProvider):
    """A fake provider that records each call and returns only bars in the window.

    The base ``FakeProvider`` ignores the requested dates; this variant filters by
    them so a test can assert that the sync asked for the right backwards window.
    """

    def __init__(self, provider_id: str, bars: list[PriceBar]) -> None:
        super().__init__(provider_id, bars=bars)
        self.windows: list[tuple[date, date]] = []

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        self.windows.append((start, end))
        return [
            bar.model_copy(update={"source": self.id})
            for bar in self._bars
            if start <= bar.date <= end
        ]

    def get_index_daily(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        self.windows.append((start, end))
        return [
            bar.model_copy(update={"source": self.id})
            for bar in self._bars
            if start <= bar.date <= end
        ]


def _data_service(
    factory: sessionmaker[Session], providers: list[FakeProvider]
) -> DataService:
    settings = _settings()
    fallback = FallbackProvider(
        providers,
        settings=settings,
        order=[provider.id for provider in providers],
        clock=_clock,
        sleeper=lambda _seconds: None,
        today_provider=lambda: TODAY,
    )
    sync = SyncService(
        session_factory=factory,
        fallback=fallback,
        settings=settings,
        today_provider=lambda: TODAY,
    )
    return DataService(
        session_factory=factory,
        sync_service=sync,
        fallback=fallback,
        settings=settings,
        today_provider=lambda: TODAY,
    )


def test_sync_symbol_extends_history_backwards(factory: sessionmaker[Session]) -> None:
    full = daily_bars(date(2024, 1, 2), 7)
    provider = _RangeProvider("a", bars=full)
    service = _service(factory, [provider])
    # Seed only the recent days, as a first shallow fetch would have stored them.
    with session_scope(factory) as session:
        SqlPriceRepository(session).upsert_many(
            "VNM", [bar for bar in full if bar.date >= date(2024, 1, 4)]
        )

    result = service.sync_symbol("VNM", start=date(2024, 1, 2))

    assert result.ok
    assert result.status == "updated"
    # The fetch reaches back to the requested start (overlapping the stored bars).
    assert (date(2024, 1, 2), TODAY) in provider.windows
    with session_scope(factory) as session:
        prices = SqlPriceRepository(session)
        assert prices.earliest_date("VNM") == date(2024, 1, 2)
        assert prices.count("VNM") == 7


def test_sync_benchmark_extends_history_backwards(
    factory: sessionmaker[Session],
) -> None:
    full = daily_bars(date(2024, 1, 2), 7, base=1000.0)
    provider = _RangeProvider("a", bars=full)
    service = _service(factory, [provider])
    with session_scope(factory) as session:
        SqlIndexRepository(session).upsert_many(
            "VNINDEX", [bar for bar in full if bar.date >= date(2024, 1, 4)]
        )

    result = service.sync_benchmark(
        BENCHMARK_BY_CODE["VNINDEX"], start=date(2024, 1, 2)
    )

    assert result.ok
    assert (date(2024, 1, 2), TODAY) in provider.windows
    with session_scope(factory) as session:
        indices = SqlIndexRepository(session)
        assert indices.earliest_date("VNINDEX") == date(2024, 1, 2)
        assert indices.count("VNINDEX") == 7


def test_get_prices_extends_to_the_requested_start(
    factory: sessionmaker[Session],
) -> None:
    full = daily_bars(date(2023, 12, 1), 40)
    provider = _RangeProvider("a", bars=full)
    service = _data_service(factory, [provider])
    with session_scope(factory) as session:
        SqlPriceRepository(session).upsert_many(
            "VNM", [bar for bar in full if bar.date >= date(2024, 1, 1)]
        )

    series = service.get_prices("VNM", start=date(2023, 12, 1), end=TODAY)

    assert series.rows[0].date == date(2023, 12, 1)
    assert series.rows[-1].date == TODAY
    with session_scope(factory) as session:
        assert SqlPriceRepository(session).earliest_date("VNM") == date(2023, 12, 1)


def test_get_index_prices_extends_to_the_requested_start(
    factory: sessionmaker[Session],
) -> None:
    full = daily_bars(date(2023, 12, 1), 40, base=1000.0)
    provider = _RangeProvider("a", bars=full)
    service = _data_service(factory, [provider])
    with session_scope(factory) as session:
        SqlIndexRepository(session).upsert_many(
            "VNINDEX", [bar for bar in full if bar.date >= date(2024, 1, 1)]
        )

    series = service.get_index_prices("VNINDEX", start=date(2023, 12, 1), end=TODAY)

    assert series.rows[0].date == date(2023, 12, 1)
    assert series.rows[-1].date == TODAY
    with session_scope(factory) as session:
        assert SqlIndexRepository(session).earliest_date("VNINDEX") == date(2023, 12, 1)


def test_get_prices_prefers_v2_adjusted_closes_when_present(
    factory: sessionmaker[Session],
) -> None:
    """The optimizer's V2-adjusted read serves close_adj and falls back to V1 otherwise."""
    from data.v2.schemas import AdjustedOHLCV
    from data.v2.store import V2Store

    service = _data_service(factory, [])
    # Seed V2 adjusted bars (close_adj differs from the raw close by the adjustment).
    v2_bars = [
        AdjustedOHLCV(
            date=date(2024, 1, 2),
            open=100.0,
            high=101.0,
            low=99.0,
            close=95.0,  # adjusted
            close_raw=100.0,  # raw
            volume=1000,
            source="ssi_statistics",
        ),
        AdjustedOHLCV(
            date=date(2024, 1, 3),
            open=96.0,
            high=97.0,
            low=94.0,
            close=98.0,
            close_raw=103.0,
            volume=1000,
            source="ssi_statistics",
        ),
    ]
    with session_scope(factory) as session:
        V2Store(session).upsert_prices(
            "VNM",
            v2_bars,
            price_adjustment_basis="ssi_adjusted",
            data_as_of=TODAY,
        )

    series = service.get_prices_preferring_v2_adjusted("VNM", start=date(2024, 1, 2), end=TODAY)

    assert series.source == "ssi_statistics"
    assert len(series.rows) == 2
    # adj_close carries the V2 adjusted close; close carries the raw price when present.
    assert series.rows[0].adj_close == pytest.approx(95.0)
    assert series.rows[0].close == pytest.approx(100.0)
    assert series.rows[1].adj_close == pytest.approx(98.0)
    assert series.rows[1].close == pytest.approx(103.0)


def test_get_prices_preferring_v2_falls_back_to_v1(
    factory: sessionmaker[Session],
) -> None:
    """A ticker with no V2-adjusted data still reads the V1 series."""
    from data.v2.store import V2Store

    service = _data_service(factory, [])
    full = daily_bars(date(2024, 1, 2), 3, base=1000.0, source="kbs")
    with session_scope(factory) as session:
        SqlPriceRepository(session).upsert_many("FPT", full)

    series = service.get_prices_preferring_v2_adjusted("FPT", start=date(2024, 1, 2), end=TODAY)

    assert len(series.rows) == 3
    assert series.source == "kbs"
    # No V2 data was written; nothing is stored in the V2 table for FPT.
    with session_scope(factory) as session:
        assert V2Store(session).get_prices("FPT") == []


def test_get_prices_preferring_v2_spot_uses_the_raw_close(
    factory: sessionmaker[Session],
) -> None:
    """The spot reader serves the V2 raw close for valuation and the adjusted close for returns."""
    from data.v2.schemas import AdjustedOHLCV
    from data.v2.store import V2Store

    service = _data_service(factory, [])
    v2_bars = [
        AdjustedOHLCV(
            date=date(2024, 1, 2),
            open=100.0,
            high=101.0,
            low=99.0,
            close=95.0,  # adjusted
            close_raw=100.0,  # raw / spot
            volume=1000,
            source="ssi_statistics",
        ),
        AdjustedOHLCV(
            date=date(2024, 1, 3),
            open=96.0,
            high=97.0,
            low=94.0,
            close=98.0,
            close_raw=103.0,
            volume=1000,
            source="ssi_statistics",
        ),
    ]
    with session_scope(factory) as session:
        V2Store(session).upsert_prices(
            "VNM", v2_bars, price_adjustment_basis="ssi_adjusted", data_as_of=TODAY
        )

    series = service.get_prices_preferring_v2_spot("VNM", start=date(2024, 1, 2), end=TODAY)

    assert series.source == "ssi_statistics"
    assert len(series.rows) == 2
    # Spot valuation reads the raw close; adj_close carries the adjusted close.
    assert series.rows[0].close == pytest.approx(100.0)
    assert series.rows[0].adj_close == pytest.approx(95.0)
    assert series.rows[1].close == pytest.approx(103.0)
    assert series.rows[1].adj_close == pytest.approx(98.0)


def test_overall_latest_price_date_spans_v1_and_v2(factory: sessionmaker[Session]) -> None:
    """The global latest date is the newest bar across both price stores."""
    from data.v2.schemas import AdjustedOHLCV
    from data.v2.store import V2Store

    service = _data_service(factory, [])
    with session_scope(factory) as session:
        SqlPriceRepository(session).upsert_many("FPT", daily_bars(date(2024, 1, 3), 2))
        V2Store(session).upsert_prices(
            "HPG",
            [
                AdjustedOHLCV(
                    date=date(2024, 1, 8),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    close_raw=100.0,
                    volume=1000,
                    source="ssi_statistics",
                )
            ],
            price_adjustment_basis="ssi_adjusted",
            data_as_of=TODAY,
        )

    assert service.overall_latest_price_date() == date(2024, 1, 8)


def test_get_prices_v2_is_v2_only_and_reports_missing(
    factory: sessionmaker[Session],
) -> None:
    """The V2-only reader never falls back to V1; a ticker without V2 data is missing."""
    from data.v2.schemas import AdjustedOHLCV
    from data.v2.store import V2Store

    service = _data_service(factory, [])
    with session_scope(factory) as session:
        # FPT has only V1 data; HPG has V2 data; ZZZ has neither.
        SqlPriceRepository(session).upsert_many("FPT", daily_bars(date(2024, 1, 2), 3))
        V2Store(session).upsert_prices(
            "HPG",
            [
                AdjustedOHLCV(
                    date=date(2024, 1, 8),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    close_raw=100.0,
                    volume=1000,
                    source="ssi_statistics",
                )
            ],
            price_adjustment_basis="ssi_adjusted",
            data_as_of=TODAY,
        )

    hpg = service.get_prices_v2("HPG", start=date(2024, 1, 2), end=TODAY)
    assert hpg.status == "ok"
    assert hpg.source == "ssi_statistics"
    assert [row.date for row in hpg.rows] == [date(2024, 1, 8)]

    # A ticker with only V1 data is "missing" from the V2 layer (no silent fallback).
    fpt = service.get_prices_v2("FPT", start=date(2024, 1, 2), end=TODAY)
    assert fpt.status == "missing"
    assert fpt.rows == []
    assert any("no V2 price data" in warning for warning in fpt.warnings)
