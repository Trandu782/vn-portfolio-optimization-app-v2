"""Persisted adjustment-quality flags: recompute correctness, staleness and offline mode."""

from __future__ import annotations

import socket
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.v2.adjustment_quality import (
    FLAGS_POLICY_VERSION,
    adjustment_quality_flag,
    policy_from_source,
)
from data.v2.analytics.universe_reader import flags_policy_current
from data.v2.precompute import (
    compute_adjustment_flags,
    recompute_adjustment_flags_offline,
)
from data.v2.precompute_schemas import AdjustmentFlagRecord, TickerRecord
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store

#: A fixed "today" that is itself a trading day, so the offline target is stable.
TODAY = date(2024, 1, 10)


def _weekdays(count: int, start: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bar(day: date, close: float, close_raw: float | None) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        close_raw=close_raw,
        volume=1000,
        source="ssi_statistics",
    )


def _seed(tmp_path: Path) -> sessionmaker[Session]:
    """Seed a temp DB: a clean name, a ratio-drift name, a reversing name and a non-member."""
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'flags.db').as_posix()}")
    create_all(engine)
    factory = create_session_factory(engine)
    days = _weekdays(5, date(2024, 1, 2))
    last = days[-1]
    clean = [_bar(days[index], 100.0 + index, 100.0 + index) for index in range(5)]
    drift = [
        _bar(days[0], 100.0, 110.0),
        _bar(days[1], 100.0, 100.0),
        _bar(days[2], 100.0, 99.0),
    ]
    reversing = [
        _bar(days[0], 100.0, None),
        _bar(days[1], 91.0, None),
        _bar(days[2], 100.0, None),
    ]
    bars_by_ticker = {
        "CLEAN": clean,
        "DRIFT": drift,
        "REVERSING": reversing,
        "NONMEMBER": clean,
    }
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(ticker=ticker, exchange="HOSE", source="test", data_as_of=last)
                for ticker in bars_by_ticker
            ]
        )
        store.replace_membership(
            "VN100", ["CLEAN", "DRIFT", "REVERSING"], as_of=last, source="test"
        )
        for ticker, bars in bars_by_ticker.items():
            store.upsert_prices(
                ticker, bars, price_adjustment_basis="ssi_adjusted", data_as_of=last
            )
    return factory


def _stored(factory: sessionmaker[Session]) -> dict[str, AdjustmentFlagRecord]:
    with session_scope(factory) as session:
        return {record.ticker: record for record in V2Store(session).list_adjustment_flags()}


def test_recomputed_flags_equal_the_policy_rules(tmp_path: Path) -> None:
    factory = _seed(tmp_path)
    with session_scope(factory) as session:
        master = V2Store(session).list_ticker_master()

    step = compute_adjustment_flags(factory, target=master[0].data_as_of, universe=master)
    assert step.ok is True
    assert step.processed == 4

    stored = _stored(factory)
    for record in master:
        with session_scope(factory) as session:
            store = V2Store(session)
            bars = store.get_prices(record.ticker)
            actions = store.get_corporate_actions(record.ticker)
        expected = adjustment_quality_flag(record.ticker, bars, actions)
        got = stored[record.ticker]
        assert got.flagged == expected.flagged
        assert got.exclude_from_group_indices == expected.exclude_from_group_indices
        assert got.reasons == expected.reasons
        assert got.dates == expected.dates

    assert stored["CLEAN"].flagged is False
    assert stored["DRIFT"].flagged is True
    assert stored["DRIFT"].exclude_from_group_indices is False
    assert stored["REVERSING"].flagged is True
    assert stored["REVERSING"].exclude_from_group_indices is True


def test_stale_rows_are_detected_until_recomputed(tmp_path: Path) -> None:
    factory = _seed(tmp_path)
    with session_scope(factory) as session:
        V2Store(session).upsert_adjustment_flags(
            [
                AdjustmentFlagRecord(
                    ticker="DRIFT",
                    severity="warning",
                    flagged=True,
                    source="ssi_statistics",
                    data_as_of=TODAY,
                    reasons=["old policy reason"],
                )
            ]
        )
        stale = V2Store(session).list_adjustment_flags()

    assert flags_policy_current(stale) is False

    report = recompute_adjustment_flags_offline(
        factory, members="VN100", today_provider=lambda: TODAY
    )
    assert report.ok is True

    current = _stored(factory)
    assert {record.ticker for record in current.values()} == {"CLEAN", "DRIFT", "REVERSING"}
    assert flags_policy_current(list(current.values())) is True
    assert all(
        policy_from_source(record.source) == FLAGS_POLICY_VERSION
        for record in current.values()
    )


def test_offline_recompute_is_idempotent(tmp_path: Path) -> None:
    factory = _seed(tmp_path)

    first = recompute_adjustment_flags_offline(
        factory, members="VN100", today_provider=lambda: TODAY
    )
    after_first = _stored(factory)
    second = recompute_adjustment_flags_offline(
        factory, members="VN100", today_provider=lambda: TODAY
    )
    after_second = _stored(factory)

    assert first.ok is True
    assert second.ok is True
    assert after_first == after_second
    # The restriction is honoured: the non-member name is never touched.
    assert set(after_first) == {"CLEAN", "DRIFT", "REVERSING"}


def test_offline_recompute_never_opens_a_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the offline recompute must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    factory = _seed(tmp_path)

    report = recompute_adjustment_flags_offline(
        factory, members="VN100", today_provider=lambda: TODAY
    )

    assert report.ok is True



def _liquidity_bar(day: date, close: float, matched_value: float) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        close_raw=None,
        volume=1000,
        matched_volume=100,
        matched_value=matched_value,
        source="ssi_statistics",
    )


def test_anomaly_on_a_thin_day_is_thin_trading() -> None:
    days = _weekdays(4, date(2024, 1, 2))
    bars = [
        _liquidity_bar(days[0], 100.0, 1e9),
        _liquidity_bar(days[1], 100.0, 1e9),
        _liquidity_bar(days[2], 120.0, 1e6),  # +20% on a near-zero-value session
        _liquidity_bar(days[3], 120.0, 1e9),
    ]
    flag = adjustment_quality_flag("THIN", bars)
    assert flag.exclude_from_group_indices is True
    assert flag.anomalies
    assert flag.anomalies[0].exclude is True
    assert flag.anomalies[0].category == "thin_trading"


def test_anomaly_on_a_normal_day_is_a_data_glitch() -> None:
    days = _weekdays(4, date(2024, 1, 2))
    bars = [
        _liquidity_bar(days[0], 100.0, 1e9),
        _liquidity_bar(days[1], 100.0, 1e9),
        _liquidity_bar(days[2], 120.0, 1e9),  # +20% on a normal-value session
        _liquidity_bar(days[3], 120.0, 1e9),
    ]
    flag = adjustment_quality_flag("GLITCH", bars)
    assert flag.exclude_from_group_indices is True
    assert flag.anomalies
    assert flag.anomalies[0].category == "data_glitch"
