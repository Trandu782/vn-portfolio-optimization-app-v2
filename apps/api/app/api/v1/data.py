"""Market-data routes: symbols, prices, quality, provider status, probe, refresh.

All routes are thin: they validate input, call one data-layer service and return a
typed response. ``/data/probe`` and ``/data/refresh`` are protected by the shared
refresh token (``VNOPT_REFRESH_TOKEN`` / ``REFRESH_TOKEN``; Vercel Cron sends it
as ``Authorization: Bearer <CRON_SECRET>``).
"""

from __future__ import annotations

import hmac
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from core.settings import Settings as CoreSettings
from core.validation import MarketDate, TickerSymbol, validate_ticker_symbol
from data.context import get_context
from data.models import (
    DataFreshness,
    PriceSeries,
    ProbeReport,
    ProviderStatus,
    QualityReport,
    RefreshResult,
    SymbolInfo,
)
from data.probe import DEFAULT_INDEX, DEFAULT_TICKERS, run_probe
from data.registry import data_providers
from data.service import DataService
from data.settings import get_settings
from data.sync import SyncService

router = APIRouter(tags=["data"])


def get_data_service() -> DataService:
    """FastAPI dependency returning the read service."""
    return get_context().service


def get_sync_service() -> SyncService:
    """FastAPI dependency returning the sync service."""
    return get_context().sync


_WEAK_TOKENS = frozenset({"change-me", "changeme", "secret"})
_MIN_PROD_TOKEN_LENGTH = 32


def require_token(
    authorization: Annotated[str | None, Header()] = None,
    x_refresh_token: Annotated[str | None, Header()] = None,
) -> None:
    """Reject the request unless it carries the configured refresh token."""
    expected = get_settings().refresh_token
    is_prod = CoreSettings().environment.strip().lower() == "production"
    if not expected or (
        is_prod
        and (
            expected.strip().lower() in _WEAK_TOKENS
            or len(expected) < _MIN_PROD_TOKEN_LENGTH
        )
    ):
        raise HTTPException(
            status_code=503,
            detail="endpoint is not configured",
        )
    provided = x_refresh_token
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid or missing refresh token")


class SymbolListResponse(BaseModel):
    """Symbols stored in the database, optionally filtered by exchange."""

    exchange: str | None
    count: int
    symbols: list[SymbolInfo]


@router.get("/symbols", response_model=SymbolListResponse)
def list_symbols(
    response: Response,
    service: Annotated[DataService, Depends(get_data_service)],
    exchange: Annotated[str | None, Query(description="HOSE, HNX or UPCoM")] = None,
) -> SymbolListResponse:
    """Return the stored symbols."""
    symbols = service.list_symbols(exchange)
    response.headers["Cache-Control"] = (
        "public, max-age=3600, s-maxage=43200, stale-while-revalidate=86400"
    )
    return SymbolListResponse(exchange=exchange, count=len(symbols), symbols=symbols)


@router.get("/prices/{symbol}", response_model=PriceSeries)
def get_prices(
    symbol: TickerSymbol,
    service: Annotated[DataService, Depends(get_data_service)],
    start: Annotated[MarketDate | None, Query()] = None,
    end: Annotated[MarketDate | None, Query()] = None,
) -> PriceSeries:
    """Return daily prices for a symbol, backfilling once if it is known."""
    return service.get_prices(symbol, start=start, end=end)


@router.get("/data/index/{index_code}", response_model=PriceSeries)
def get_index_prices(
    index_code: TickerSymbol,
    service: Annotated[DataService, Depends(get_data_service)],
    start: Annotated[MarketDate | None, Query()] = None,
    end: Annotated[MarketDate | None, Query()] = None,
) -> PriceSeries:
    """Return daily prices for a benchmark index (VNINDEX, VN30, ...)."""
    return service.get_index_prices(index_code, start=start, end=end)


@router.get("/data/quality/{symbol}", response_model=QualityReport)
def get_quality(
    symbol: TickerSymbol,
    service: Annotated[DataService, Depends(get_data_service)],
) -> QualityReport:
    """Run every registered quality check for ``symbol``."""
    return service.get_quality(symbol)


@router.get("/data/providers/status", response_model=list[ProviderStatus])
def providers_status(
    service: Annotated[DataService, Depends(get_data_service)],
) -> list[ProviderStatus]:
    """Return each provider's health, last error and circuit-breaker state."""
    return service.provider_status()


@router.get("/data/freshness", response_model=DataFreshness)
def data_freshness(
    response: Response,
    service: Annotated[DataService, Depends(get_data_service)],
) -> DataFreshness:
    """Return the latest stored price date and the freshest price source."""
    freshness = service.data_freshness()
    response.headers["Cache-Control"] = (
        "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
    )
    return freshness


class ProviderCatalogueEntry(BaseModel):
    """Registry metadata for one provider (id, name, description, params)."""

    id: str
    name: str
    description: str
    parameter_schema: dict[str, Any] | None


@router.get("/data/providers", response_model=list[ProviderCatalogueEntry])
def list_providers() -> list[ProviderCatalogueEntry]:
    """Publish the provider catalogue from the registry."""
    return [
        ProviderCatalogueEntry(
            id=info.id,
            name=info.name,
            description=info.description,
            parameter_schema=info.parameter_schema,
        )
        for info in data_providers.describe()
    ]


@router.get("/data/probe", response_model=ProbeReport, dependencies=[Depends(require_token)])
def probe_providers(
    tickers: Annotated[str, Query()] = ",".join(DEFAULT_TICKERS),
    index_code: TickerSymbol = DEFAULT_INDEX,
    start: Annotated[MarketDate | None, Query()] = None,
    end: Annotated[MarketDate | None, Query()] = None,
    years: Annotated[int, Query(ge=1, le=20)] = 5,
) -> ProbeReport:
    """Call every provider and report what works on the current (hosted) network."""
    context = get_context()
    range_end = end or date.today()
    range_start = start or (range_end - timedelta(days=365 * years))
    raw_items = [item for item in tickers.split(",") if item.strip()]
    if len(raw_items) > 10:
        raise HTTPException(status_code=422, detail="at most 10 tickers per probe request")
    try:
        ticker_list = [validate_ticker_symbol(item, field_name="tickers") for item in raw_items]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return run_probe(
        context.providers,
        start=range_start,
        end=range_end,
        tickers=ticker_list,
        index_code=index_code,
    )


# Vercel Cron issues a GET request, so the sync is reachable via GET as well as
# POST. Both are protected by the same token (Vercel sends
# "Authorization: Bearer ${CRON_SECRET}"; set CRON_SECRET = VNOPT_REFRESH_TOKEN).
@router.get(
    "/data/refresh", response_model=RefreshResult, dependencies=[Depends(require_token)]
)
@router.post(
    "/data/refresh", response_model=RefreshResult, dependencies=[Depends(require_token)]
)
def refresh(
    sync: Annotated[SyncService, Depends(get_sync_service)],
    cursor: Annotated[int, Query(ge=0, description="Resume from a prior call.")] = 0,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    time_budget: Annotated[float | None, Query(gt=0, le=110.0)] = None,
) -> RefreshResult:
    """Run a bounded incremental sync batch and report what remains."""
    return sync.refresh_batch(cursor=cursor, limit=limit, time_budget=time_budget)


class BackfillRequest(BaseModel):
    """Symbols to backfill on demand (the Universe page's Refresh data action)."""

    symbols: list[TickerSymbol] = Field(
        default_factory=list, max_length=25, description="Ticker codes to sync."
    )
    history_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="History depth to fetch when a symbol has no stored bars.",
    )


class BackfillSymbolResult(BaseModel):
    """Outcome of syncing one symbol."""

    symbol: str
    ok: bool
    status: str
    provider: str | None = None
    rows: int = 0
    message: str | None = None


class BackfillResponse(BaseModel):
    """Per-symbol outcome of an on-demand backfill."""

    requested: int
    synced: int
    results: list[BackfillSymbolResult]


@router.post(
    "/data/backfill",
    response_model=BackfillResponse,
    dependencies=[Depends(require_token)],
)
def backfill(
    request: BackfillRequest,
    sync: Annotated[SyncService, Depends(get_sync_service)],
) -> BackfillResponse:
    """Run an incremental on-demand backfill for the requested symbols."""
    codes = [code.strip().upper() for code in request.symbols if code.strip()]
    results: list[BackfillSymbolResult] = []
    for code in codes:
        outcome = sync.sync_symbol(
            code, history_days=request.history_days, allow_unknown=True
        )
        message = outcome.message
        if message is None and outcome.warnings:
            message = "; ".join(outcome.warnings)
        results.append(
            BackfillSymbolResult(
                symbol=outcome.symbol,
                ok=outcome.ok,
                status=outcome.status,
                provider=outcome.provider,
                rows=outcome.rows,
                message=message,
            )
        )
    return BackfillResponse(
        requested=len(codes),
        synced=sum(1 for result in results if result.ok),
        results=results,
    )
