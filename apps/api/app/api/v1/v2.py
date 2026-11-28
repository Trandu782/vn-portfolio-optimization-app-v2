"""V2 precomputed-data routes: ticker snapshot, coverage, universe filter, sectors.

Thin routes: validate input, call one data-layer helper and return a typed response.
The universe filter calls the same ``filter_universe`` the analytics engine uses, so
identical settings return identical tickers; the sector list powers the Optimize
multi-select with total and preset-passing counts. Both read only the V2 tables,
never the network, and return ``data_as_of`` and the basis flags. An unknown preset,
index, exchange or sector name maps to a 422.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Response

from core.validation import MarketDate, TickerSymbol
from data.context import get_context
from data.v2.analytics.index import WEIGHTING_EQUAL, WEIGHTING_MARKET_CAP
from data.v2.analytics.liquidity import DEFAULT_PRESET_ID
from data.v2.analytics.schemas import AnalyticsPayload
from data.v2.analytics.service import AnalyticsRequest, AnalyticsService
from data.v2.analytics.universe_service import (
    SectorListResponse,
    UniverseFilterRequest,
    UniverseFilterResponse,
    UniverseService,
)
from data.v2.fundamentals import FundamentalsComparison, FundamentalsService, PeerVariant
from data.v2.precompute_schemas import CoverageSummary, TickerSnapshot
from data.v2.reader import sector_coverage, ticker_snapshot

router = APIRouter(tags=["v2"])

_V2_CACHE_CONTROL = "public, max-age=3600, s-maxage=43200, stale-while-revalidate=86400"


@router.get("/v2/ticker/{symbol}", response_model=TickerSnapshot)
def get_ticker_snapshot(
    symbol: TickerSymbol,
    response: Response,
    start: Annotated[MarketDate | None, Query()] = None,
    end: Annotated[MarketDate | None, Query()] = None,
) -> TickerSnapshot:
    """Return adjusted returns, liquidity, market cap and sector for ``symbol``."""
    snapshot = ticker_snapshot(get_context().session_factory, symbol, start, end)
    response.headers["Cache-Control"] = _V2_CACHE_CONTROL
    return snapshot


@router.get("/v2/coverage", response_model=CoverageSummary)
def get_sector_coverage(response: Response) -> CoverageSummary:
    """Return the precomputed universe's sector coverage, with every gap listed."""
    coverage = sector_coverage(get_context().session_factory)
    response.headers["Cache-Control"] = _V2_CACHE_CONTROL
    return coverage


@router.get("/v2/universe", response_model=UniverseFilterResponse)
def get_universe(
    response: Response,
    preset: Annotated[str, Query()] = DEFAULT_PRESET_ID,
    sectors: Annotated[list[str] | None, Query(max_length=50)] = None,
    indexes: Annotated[list[str] | None, Query(max_length=10)] = None,
    exchange: Annotated[str | None, Query()] = None,
    as_of: Annotated[MarketDate | None, Query()] = None,
    exclude_adjustment_flagged: Annotated[bool, Query()] = False,
) -> UniverseFilterResponse:
    """Return the tickers that pass the preset and facets, using ``filter_universe``."""
    request = UniverseFilterRequest(
        preset=preset,
        sectors=sectors or [],
        indexes=indexes or [],
        exchange=exchange,
        as_of=as_of,
        exclude_adjustment_flagged=exclude_adjustment_flagged,
    )
    try:
        payload = UniverseService(get_context().session_factory).filter(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Cache-Control"] = _V2_CACHE_CONTROL
    return payload


@router.get("/v2/sectors", response_model=SectorListResponse)
def get_sectors(
    response: Response,
    preset: Annotated[str, Query()] = DEFAULT_PRESET_ID,
) -> SectorListResponse:
    """Return ICB level-2 sectors with total and preset-passing constituent counts."""
    try:
        payload = UniverseService(get_context().session_factory).sectors(preset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Cache-Control"] = _V2_CACHE_CONTROL
    return payload


class AnalyticsResponse(AnalyticsPayload):
    """The analytics payload plus the per-response cache/timing metadata."""

    served_from_cache: bool = False
    elapsed_ms: float = 0.0


@router.get("/v2/analytics", response_model=AnalyticsResponse)
def get_analytics(
    response: Response,
    benchmark: Annotated[str, Query()] = "VNINDEX",
    timeframe: Annotated[str, Query()] = "1Y",
    custom_start: Annotated[MarketDate | None, Query()] = None,
    custom_end: Annotated[MarketDate | None, Query()] = None,
    grouping: Annotated[str, Query()] = "sector",
    liquidity_preset: Annotated[str, Query()] = DEFAULT_PRESET_ID,
    indexes: Annotated[list[str] | None, Query(max_length=10)] = None,
    exchange: Annotated[str | None, Query()] = None,
    weighting: Annotated[str, Query()] = WEIGHTING_MARKET_CAP,
    cap_percent: Annotated[float | None, Query()] = None,
    include_default_excluded: Annotated[bool, Query()] = False,
    exclude_adjustment_flagged: Annotated[bool, Query()] = False,
) -> AnalyticsResponse:
    """Return the Sector Analysis payload for the selected benchmark, window and facets."""
    if weighting not in (WEIGHTING_MARKET_CAP, WEIGHTING_EQUAL):
        raise HTTPException(
            status_code=422,
            detail=f"unknown weighting {weighting!r}; expected market_cap or equal",
        )
    if cap_percent is not None and not (0.0 < cap_percent <= 100.0):
        raise HTTPException(
            status_code=422,
            detail="cap_percent must be null (no cap) or a number in (0, 100]",
        )
    if timeframe.strip().upper() == "CUSTOM" and (custom_start is None or custom_end is None):
        raise HTTPException(
            status_code=422,
            detail="a custom timeframe needs both custom_start and custom_end",
        )
    if custom_start is not None and custom_end is not None and custom_start > custom_end:
        raise HTTPException(
            status_code=422,
            detail="custom_start must not be after custom_end",
        )
    request = AnalyticsRequest(
        benchmark=benchmark,
        timeframe=timeframe,
        custom_start=custom_start,
        grouping=grouping,
        liquidity_preset=liquidity_preset,
        sectors=[],
        indexes=indexes or [],
        exchange=exchange,
        weighting=weighting,
        single_stock_cap=(cap_percent / 100.0) if cap_percent is not None else None,
        end_date=custom_end,
        exclude_adjustment_flagged=exclude_adjustment_flagged,
        include_default_excluded=include_default_excluded,
    )
    try:
        payload, from_cache, elapsed = AnalyticsService(
            get_context().session_factory
        ).build_cached(request)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Cache-Control"] = _V2_CACHE_CONTROL
    return AnalyticsResponse(
        **payload.model_dump(), served_from_cache=from_cache, elapsed_ms=elapsed
    )


@router.get("/v2/fundamentals/{symbol}", response_model=FundamentalsComparison)
def get_fundamentals(
    symbol: TickerSymbol,
    response: Response,
    period: Annotated[MarketDate | None, Query()] = None,
    period_type: Annotated[str | None, Query()] = None,
    peer_variant: Annotated[str, Query()] = "all",
    preset: Annotated[str, Query()] = DEFAULT_PRESET_ID,
) -> FundamentalsComparison:
    """Return a ticker's ratio comparison against its sector peers.

    Defaults to the ticker's latest stored period and the "all peers" variant; a
    ``peer_variant`` of ``liquidity``/``vn100`` narrows the peer set (never across
    sectors, so financials are not compared with non-financials).
    """
    service = FundamentalsService(get_context().session_factory)
    if period is None or period_type is None:
        available = service.periods(symbol)
        if not available:
            raise HTTPException(
                status_code=404,
                detail=f"no financial ratios stored for {symbol.strip().upper()}",
            )
        latest_period, latest_type = available[0]
        period = period or latest_period
        period_type = period_type or latest_type
    if peer_variant not in {"all", "liquidity", "vn100"}:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown peer_variant {peer_variant!r}; expected all, liquidity or vn100"
            ),
        )
    try:
        comparison = service.compare(
            symbol,
            period=period,
            period_type=period_type,
            variant=cast(PeerVariant, peer_variant),
            preset_id=preset,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Cache-Control"] = _V2_CACHE_CONTROL
    return comparison
