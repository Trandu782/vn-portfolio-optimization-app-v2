"""Per-ticker adjustment-quality flag and the explained/unexplained split."""

from __future__ import annotations

from datetime import date, timedelta

from data.v2.adjustment_quality import (
    adjustment_quality_flag,
    find_adjustment_anomalies,
    widest_daily_limit,
)
from data.v2.schemas import AdjustedOHLCV, CorporateAction


def _bar(
    day: date, close: float, *, close_raw: float | None = None, volume: int = 1000
) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        close_raw=close_raw,
        volume=volume,
        source="ssi_statistics",
    )


def _weekdays(count: int, start: date = date(2024, 1, 2)) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _ratio_jump_bars() -> list[AdjustedOHLCV]:
    days = _weekdays(3)
    return [
        _bar(days[0], 100.0, close_raw=110.0),
        _bar(days[1], 100.0, close_raw=100.0),
        _bar(days[2], 100.0, close_raw=99.0),
    ]


def test_the_widest_daily_limit_is_upcom_15_percent() -> None:
    assert abs(widest_daily_limit() - 0.15) < 1e-12


def test_a_clean_series_is_not_flagged() -> None:
    days = _weekdays(4)
    bars = [_bar(day, 100.0 + index) for index, day in enumerate(days)]
    flag = adjustment_quality_flag("VCB", bars)
    assert not flag.flagged
    assert flag.severity == "ok"
    assert flag.reasons == []


def test_an_unexplained_jump_beyond_the_widest_limit_is_flagged() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100.0), _bar(days[1], 120.0), _bar(days[2], 121.0)]
    flag = adjustment_quality_flag("XYZ", bars)
    assert flag.flagged
    assert flag.exclude_from_group_indices
    assert any("price moved" in reason for reason in flag.reasons)
    (anomaly,) = find_adjustment_anomalies("XYZ", bars)
    assert anomaly.explained is None


def test_a_jump_near_a_known_ex_date_is_not_flagged_as_a_move() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100.0), _bar(days[1], 120.0), _bar(days[2], 121.0)]
    action = CorporateAction(
        ticker="XYZ", event_type="ISS", exright_date=days[1], ratio=0.2, source="ssi"
    )
    anomalies = find_adjustment_anomalies("XYZ", bars, [action])
    assert not any("price moved" in anomaly.reason for anomaly in anomalies)


def test_a_documented_vgi_ratio_drift_is_labelled_explained() -> None:
    flag = adjustment_quality_flag("VGI", _ratio_jump_bars())
    assert flag.flagged
    assert any("drifted apart" in reason for reason in flag.reasons)
    anomalies = find_adjustment_anomalies("VGI", _ratio_jump_bars())
    assert anomalies and all(anomaly.explained is not None for anomaly in anomalies)


def test_hpg_missing_bonus_drift_is_labelled_explained() -> None:
    flag = adjustment_quality_flag("HPG", _ratio_jump_bars())
    assert flag.flagged
    assert any("drifted apart" in reason for reason in flag.reasons)
    anomalies = find_adjustment_anomalies("HPG", _ratio_jump_bars())
    assert anomalies and all(anomaly.explained is not None for anomaly in anomalies)


def test_an_unexplained_ratio_drift_is_labelled_unexplained() -> None:
    flag = adjustment_quality_flag("VCB", _ratio_jump_bars())
    assert flag.flagged
    assert any("drifted apart" in reason for reason in flag.reasons)
    anomalies = find_adjustment_anomalies("VCB", _ratio_jump_bars())
    assert anomalies and all(anomaly.explained is None for anomaly in anomalies)


def test_a_cash_dividend_reconciliation_difference_is_flagged() -> None:
    days = _weekdays(3)
    # The raw close drops ~10% (a 10 VND dividend on 100) while the adjusted close only
    # drops ~3%, so the adjustment did not remove the full dividend.
    bars = [
        _bar(days[0], 100.0, close_raw=100.0),
        _bar(days[1], 97.0, close_raw=90.0),
        _bar(days[2], 97.0, close_raw=90.0),
    ]
    action = CorporateAction(
        ticker="XYZ", event_type="DIV", exright_date=days[1], value=10.0, source="ssi"
    )
    flag = adjustment_quality_flag("XYZ", bars, [action])
    assert flag.flagged
    assert flag.exclude_from_group_indices
    assert any("did not match" in reason for reason in flag.reasons)


def test_a_plain_ratio_drift_is_flagged_but_does_not_exclude() -> None:
    flag = adjustment_quality_flag("VCB", _ratio_jump_bars())
    assert flag.flagged
    assert not flag.exclude_from_group_indices


def test_a_reversing_adjusted_move_is_excluded() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100.0), _bar(days[1], 91.0), _bar(days[2], 100.0)]
    flag = adjustment_quality_flag("ABC", bars)
    assert flag.flagged
    assert flag.exclude_from_group_indices
    assert any("then reversed" in reason for reason in flag.reasons)


def test_a_matching_reconciliation_is_not_flagged() -> None:
    days = _weekdays(3)
    # Raw price drops ~9.09% at the ex-date while the adjusted close stays flat: the
    # action (10% bonus) is removed correctly, so there is nothing to flag.
    bars = [
        _bar(days[0], 100.0, close_raw=100.0),
        _bar(days[1], 100.0, close_raw=90.91),
        _bar(days[2], 100.0, close_raw=90.91),
    ]
    action = CorporateAction(
        ticker="VCB", event_type="ISS", exright_date=days[1], ratio=0.10, source="ssi"
    )
    flag = adjustment_quality_flag("VCB", bars, [action])
    assert not flag.flagged
