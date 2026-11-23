"""Shared parsing helpers for the V2 adapters.

Kept separate from the HTTP base so each adapter file only describes *where* a
resource lives, while these helpers do the defensive normalization every source
needs (bar building, range trimming, generic ratio extraction).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal

from data.errors import EmptyResultError, SchemaError
from data.v2.providers.base import (
    CLOSE_KEYS,
    DATE_KEYS,
    HIGH_KEYS,
    LOW_KEYS,
    OPEN_KEYS,
    VALUE_KEYS,
    VOLUME_KEYS,
    coerce_date,
    coerce_float,
    coerce_int,
    pick,
)
from data.v2.schemas import AdjustedOHLCV, FinancialRatios

#: Keys some upstreams use for order-matching volume (separate from put-through).
MATCHED_VOLUME_KEYS: tuple[str, ...] = ("matchedVolume", "matched_volume", "nmVolume")

#: Row keys that describe the reporting period rather than a ratio.
_PERIOD_KEYS: tuple[str, ...] = ("period", "year", "reportDate", "report_date", "date", "t")
_TICKER_KEYS: set[str] = {"ticker", "tickerCode", "symbol", "code"}


def numeric(row: Mapping[str, Any], keys: Sequence[str], default: float) -> float:
    """Return ``row[keys]`` as a float, or ``default`` when absent."""
    raw = pick(row, keys, required=False)
    return coerce_float(raw) if raw is not None else default


def make_bar(row: Mapping[str, Any], *, provider: str) -> AdjustedOHLCV:
    """Build an :class:`AdjustedOHLCV` from one upstream row."""
    try:
        day = coerce_date(pick(row, DATE_KEYS))
        close = coerce_float(pick(row, CLOSE_KEYS))
        open_price = numeric(row, OPEN_KEYS, close)
        high = numeric(row, HIGH_KEYS, close)
        low = numeric(row, LOW_KEYS, close)
        volume = coerce_int(numeric(row, VOLUME_KEYS, 0.0))
        matched_raw = pick(row, MATCHED_VOLUME_KEYS, required=False)
        value_raw = pick(row, VALUE_KEYS, required=False)
    except (KeyError, ValueError, TypeError) as exc:
        raise SchemaError(
            f"{provider} row does not match the documented schema: {exc}",
            provider=provider,
            cause=exc,
        ) from exc
    return AdjustedOHLCV(
        date=day,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        matched_volume=coerce_int(matched_raw) if matched_raw is not None else None,
        value=coerce_float(value_raw) if value_raw is not None else None,
        source=provider,
    )


def finalize_bars(
    bars: Sequence[AdjustedOHLCV], *, start: date, end: date, provider: str
) -> list[AdjustedOHLCV]:
    """Trim to ``[start, end]``, drop out-of-range rows, sort and de-duplicate."""
    if not bars:
        raise EmptyResultError("provider returned no rows", provider=provider)
    in_range = [bar for bar in bars if start <= bar.date <= end]
    by_date = {bar.date: bar for bar in in_range}
    if not by_date:
        raise EmptyResultError("provider returned no rows in range", provider=provider)
    return [by_date[day] for day in sorted(by_date)]


def parse_financial_ratios(
    payload: Any,
    *,
    ticker: str,
    provider: str,
    period_type: Literal["annual", "quarter", "ttm"] = "quarter",
) -> list[FinancialRatios]:
    """Extract normalized ratio records from a generic list-of-periods payload.

    Percentages are passed through as 0-100 numbers (upstream values are already
    in percent for the endpoints this feeds). A row without a usable period or
    without any numeric ratio is skipped; no parsable rows raises ``SchemaError``.
    """
    rows = _ratio_rows(payload, provider=provider)
    records: list[FinancialRatios] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        period_raw = pick(row, _PERIOD_KEYS, required=False)
        if period_raw is None:
            continue
        period = _coerce_period(period_raw)
        if period is None:
            continue
        ratios = _numeric_ratios(row)
        if not ratios:
            continue
        records.append(
            FinancialRatios(
                ticker=ticker,
                period=period,
                period_type=period_type,
                provider=provider,
                ratios=ratios,
            )
        )
    if not records:
        raise SchemaError(f"{provider} returned no parsable ratio periods", provider=provider)
    return records


def _coerce_period(value: Any) -> date | None:
    """Coerce a reporting period, treating a bare 4-digit year as fiscal year-end."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 1900 <= value <= 2100:
        return date(value, 12, 31)
    text = str(value).strip()
    if text.isdigit() and len(text) == 4 and 1900 <= int(text) <= 2100:
        return date(int(text), 12, 31)
    try:
        return coerce_date(value)
    except ValueError:
        return None


def _ratio_rows(payload: Any, *, provider: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("data", "Data", "ratios"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return inner
            if isinstance(inner, Mapping):
                nested = inner.get("data")
                if isinstance(nested, list):
                    return nested
        return [payload]
    raise SchemaError(f"{provider} ratios payload is not a list", provider=provider)


def _numeric_ratios(row: Mapping[str, Any]) -> dict[str, float | None]:
    ratios: dict[str, float | None] = {}
    for key, value in row.items():
        name = str(key)
        if name in _PERIOD_KEYS or name in _TICKER_KEYS:
            continue
        if isinstance(value, bool) or value is None:
            ratios[name] = None
        elif isinstance(value, (int, float)):
            ratios[name] = float(value)
        elif isinstance(value, str):
            if value.strip() == "":
                continue
            try:
                ratios[name] = float(value)
            except ValueError:
                continue
    return ratios


__all__ = ["MATCHED_VOLUME_KEYS", "finalize_bars", "make_bar", "numeric", "parse_financial_ratios"]
