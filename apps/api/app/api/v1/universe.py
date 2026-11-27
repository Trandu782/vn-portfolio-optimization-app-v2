"""Universe selection routes: filter options, presets and building the universe.

The routes are thin: they resolve a symbol list (explicit tickers and/or an index
preset), ask the data layer for prices (backfilling on demand), hand the series to
:func:`core.universe.build_universe` and serialise the result. Filter definitions
come from the core registry, so the UI renders options it never hardcodes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from app.api.v1.data import get_data_service
from core.market_rules import DEFAULT_MARKET_RULES
from core.universe import (
    DailyBar,
    FilterSpec,
    Matrix,
    SymbolSeries,
    UniverseBuildResult,
    build_filters,
    build_universe,
    normalize_exchange,
    universe_filters,
)
from core.validation import MarketDate, TickerSymbol, format_validation_error
from data.calendar import last_trading_day, trading_days_between
from data.models import PriceBar
from data.presets import INDEX_PRESETS, PRESET_BY_CODE
from data.service import DataService
from data.settings import get_settings

router = APIRouter(tags=["universe"])

#: ``SymbolInfo.type`` values that mark a security as no longer tradable.
_DELISTED_TYPES = frozenset({"delisted", "delisting", "removed"})
#: ``SymbolInfo.type`` values that authoritatively mark a security as suspended/halted.
#: A trailing price bar is **not** evidence of suspension (see ``_has_stale_bars``).
_SUSPENDED_TYPES = frozenset({"suspended", "halted"})


class FilterOption(BaseModel):
    """Registry metadata for one universe filter."""

    id: str
    name: str
    description: str
    parameter_schema: dict[str, Any] | None


class PresetOption(BaseModel):
    """A curated index-based universe preset."""

    id: str
    name: str
    description: str


class UniverseOptionsResponse(BaseModel):
    """Filter catalogue and available presets, published for the UI to render."""

    filters: list[FilterOption]
    presets: list[PresetOption]


class UniverseFilterRequest(BaseModel):
    """One filter to apply, with its parameters."""

    id: str = Field(..., description="Filter id from /universe/options.")
    params: dict[str, Any] = Field(default_factory=dict)


class UniverseBuildRequest(BaseModel):
    """Inputs for building the universe."""

    symbols: list[TickerSymbol] = Field(
        default_factory=list, max_length=200, description="Explicit ticker codes."
    )
    preset: str | None = Field(default=None, description="Index preset, for example VN30.")
    filters: list[UniverseFilterRequest] = Field(default_factory=list, max_length=20)
    start: MarketDate
    end: MarketDate
    adv_sessions: int = Field(
        default=20, ge=1, le=252, description="Sessions used for the ADV metric."
    )


class DroppedTickerResponse(BaseModel):
    """A ticker removed from the universe, with the reason and responsible filter."""

    code: str
    reason: str
    filter: str | None = None


class QualityFlagsResponse(BaseModel):
    """Data-quality signals for a kept symbol."""

    suspended: bool
    delisted: bool
    missing_data: bool
    illiquid: bool


class MatrixResponse(BaseModel):
    """A date x symbol matrix serialised as rows (``null`` marks a missing value)."""

    dates: list[str]
    columns: list[str]
    data: list[list[float | None]]


class UniverseBuildResponse(BaseModel):
    """The aligned universe dataset plus provenance for kept and dropped tickers."""

    start: date
    end: date
    symbols: list[str]
    adv_by_symbol: dict[str, float]
    quality_flags: dict[str, QualityFlagsResponse]
    dropped: list[DroppedTickerResponse]
    filters_applied: list[str]
    price_matrix: MatrixResponse
    returns_matrix: MatrixResponse


class PresetResponse(BaseModel):
    """The member codes of a curated preset."""

    index_code: str
    symbols: list[str]
    count: int


@router.get("/universe/options", response_model=UniverseOptionsResponse)
def read_universe_options(response: Response) -> UniverseOptionsResponse:
    """Publish the filter catalogue (from the registry) and the available presets."""
    response.headers["Cache-Control"] = (
        "public, max-age=300, s-maxage=3600, stale-while-revalidate=7200"
    )
    return UniverseOptionsResponse(
        filters=[
            FilterOption(
                id=info.id,
                name=info.name,
                description=info.description,
                parameter_schema=info.parameter_schema,
            )
            for info in universe_filters.describe()
        ],
        presets=[
            PresetOption(id=preset.code, name=preset.name, description=preset.description)
            for preset in INDEX_PRESETS
        ],
    )


@router.get("/universe/presets/{index_code}", response_model=PresetResponse)
def read_preset(
    index_code: str,
    service: Annotated[DataService, Depends(get_data_service)],
) -> PresetResponse:
    """Return a curated preset's members, populating them on first use."""
    code = index_code.strip().upper()
    if code not in PRESET_BY_CODE:
        raise HTTPException(status_code=404, detail=f"unknown preset {code!r}")
    symbols = service.get_index_constituents(code)
    if not symbols:
        raise HTTPException(
            status_code=503, detail=f"constituents for {code} are temporarily unavailable"
        )
    return PresetResponse(index_code=code, symbols=symbols, count=len(symbols))


@router.post("/universe/build", response_model=UniverseBuildResponse)
def build_universe_endpoint(
    request: UniverseBuildRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> UniverseBuildResponse:
    """Filter the requested symbols (and preset) and return the aligned universe."""
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start must not be after end")

    codes = _resolve_symbols(request, service)
    if not codes:
        raise HTTPException(status_code=422, detail="provide at least one symbol or a preset")

    try:
        filters = build_filters(
            [FilterSpec(item.id, item.params) for item in request.filters]
        )
    except KeyError as exc:
        identifier = exc.args[0] if exc.args else "?"
        raise HTTPException(
            status_code=422, detail=f"unknown filter id {identifier!r}"
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid filter parameters: {format_validation_error(exc)}",
        ) from exc

    series, _sources = _load_symbol_series_batch(
        service, codes, request.start, request.end
    )
    result = build_universe(
        series, filters, request.start, request.end, adv_sessions=request.adv_sessions
    )
    return _to_response(result)


def _resolve_symbols(request: UniverseBuildRequest, service: DataService) -> list[str]:
    """Return the deduplicated union of explicit symbols and preset members."""
    codes: list[str] = []
    seen: set[str] = set()
    for raw in request.symbols:
        code = raw.strip().upper()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    if request.preset:
        preset_code = request.preset.strip().upper()
        if preset_code not in PRESET_BY_CODE:
            raise HTTPException(status_code=422, detail=f"unknown preset {preset_code!r}")
        for code in service.get_index_constituents(preset_code):
            if code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def _load_symbol_series_batch(
    service: DataService, codes: Sequence[str], start: date, end: date
) -> tuple[list[SymbolSeries], dict[str, str]]:
    """Load V2 series for ``codes`` in one batched query and return ``(series, sources)``."""
    price_by_code = service.get_prices_v2_batch(codes, start=start, end=end)
    series: list[SymbolSeries] = []
    sources: dict[str, str] = {}
    for code in codes:
        key = code.upper()
        info = service.get_symbol(code)
        exchange = normalize_exchange(info.exchange) if info and info.exchange else "HOSE"
        price_series = price_by_code.get(key)
        rows = price_series.rows if price_series is not None else []
        if price_series is not None and price_series.source:
            sources[key] = price_series.source
        bars = tuple(
            DailyBar(
                date=row.date,
                close=row.close,
                adj_close=row.adj_close,
                volume=row.volume,
                value=row.value,
            )
            for row in rows
            if start <= row.date <= end
        )
        security_type = (info.type or "").strip().lower() if info is not None else ""
        series.append(
            SymbolSeries(
                code=code,
                exchange=exchange,
                bars=bars,
                suspended=security_type in _SUSPENDED_TYPES,
                delisted=security_type in _DELISTED_TYPES,
                stale=_has_stale_bars(rows, end),
            )
        )
    return series, sources


def _load_symbol_series(
    service: DataService, code: str, start: date, end: date
) -> SymbolSeries:
    """Load one symbol's V2 series and derive its authoritative/staleness flags."""
    info = service.get_symbol(code)
    exchange = normalize_exchange(info.exchange) if info and info.exchange else "HOSE"
    price_series = service.get_prices_v2(code, start=start, end=end)
    bars = tuple(
        DailyBar(
            date=row.date,
            close=row.close,
            adj_close=row.adj_close,
            volume=row.volume,
            value=row.value,
        )
        for row in price_series.rows
        if start <= row.date <= end
    )
    security_type = (info.type or "").strip().lower() if info is not None else ""
    return SymbolSeries(
        code=code,
        exchange=exchange,
        bars=bars,
        suspended=security_type in _SUSPENDED_TYPES,
        delisted=security_type in _DELISTED_TYPES,
        stale=_has_stale_bars(price_series.rows, end),
    )


def _has_stale_bars(rows: list[PriceBar], end: date) -> bool:
    """Flag a symbol whose latest bar trails the range end (stale, not suspended).

    A current symbol has a bar on the last trading day on or before ``end``; one
    whose latest bar is several sessions earlier has stale/incomplete history (a
    backfill that has not reached ``end`` yet). This is a **data-quality** signal: it
    is reported as ``stale_price_data`` / a stale warning and is never interpreted as
    an exchange suspension. The check is relative to ``end`` so historical ranges are
    not misflagged.
    """
    if not rows:
        return False
    latest = max(row.date for row in rows)
    holidays = DEFAULT_MARKET_RULES.trading_holidays
    reference = last_trading_day(end, holidays)
    if latest >= reference:
        return False
    missing = trading_days_between(latest + timedelta(days=1), reference, holidays)
    return len(missing) > get_settings().stale_tolerance_days


def _stale_warnings(result: UniverseBuildResult) -> list[str]:
    """Return one warning per kept symbol whose latest V2 bar trails the window end.

    Stale history is surfaced explicitly instead of being used silently; it is a
    data-availability problem (an incomplete V2 backfill), never a suspension.
    """
    return [
        f"{code}: stale V2 price data (the latest bar trails {result.end.isoformat()})"
        for code, flags in result.quality_flags.items()
        if flags.stale
    ]


def _to_response(result: UniverseBuildResult) -> UniverseBuildResponse:
    """Convert the core result (numpy matrices) into the JSON response model."""
    columns = list(result.symbols)
    return UniverseBuildResponse(
        start=result.start,
        end=result.end,
        symbols=columns,
        adv_by_symbol={code: float(value) for code, value in result.adv_by_symbol.items()},
        quality_flags={
            code: QualityFlagsResponse(
                suspended=flags.suspended,
                delisted=flags.delisted,
                missing_data=flags.missing_data,
                illiquid=flags.illiquid,
            )
            for code, flags in result.quality_flags.items()
        },
        dropped=[
            DroppedTickerResponse(code=item.code, reason=item.reason, filter=item.filter_id)
            for item in result.dropped
        ],
        filters_applied=list(result.filters_applied),
        price_matrix=_matrix(result.dates, columns, result.price_matrix),
        returns_matrix=_matrix(result.returns_dates, columns, result.returns_matrix),
    )


def _matrix(dates: tuple[date, ...], columns: list[str], values: Matrix) -> MatrixResponse:
    """Serialise an aligned matrix, turning ``NaN`` into ``None`` for JSON."""
    data: list[list[float | None]] = []
    for row in values.tolist():
        data.append([None if math.isnan(value) else float(value) for value in row])
    return MatrixResponse(
        dates=[day.isoformat() for day in dates],
        columns=columns,
        data=data,
    )

