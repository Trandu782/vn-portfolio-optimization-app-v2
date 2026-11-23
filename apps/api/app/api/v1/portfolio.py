"""Portfolio valuation endpoint.

``POST /api/v1/portfolio/evaluate`` values the user's holdings at the latest
prices, returning market value and weight per holding, the total (including
cash), data freshness (with the serving provider) and warnings.

The route is thin. Structure validation (unique symbols, whole-number shares,
non-negative VND amounts) lives in ``core.portfolio``. Prices come from the data
layer's V2-spot reader: the latest V2 **raw** close is used when V2 has a series
for the ticker (so the freshest bar is served even when V1 lags), and the series
falls back to V1 only for a symbol without V2 data. A holding whose latest bar
trails the global latest session across the database is flagged ``stale (date)``
in its ``Notes``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.data import get_data_service
from app.api.v1.universe import _looks_suspended
from core.portfolio import (
    Holding,
    Portfolio,
    PortfolioValuation,
    portfolio_value_and_weights,
)
from core.universe import DailyBar, average_daily_value
from data.models import PriceBar, PriceSeries
from data.service import DataService

router = APIRouter(tags=["portfolio"])

#: Sessions used for the illiquid warning (mirrors the universe quality flag).
_ILLIQUIDITY_SESSIONS = 20
#: Flag a holding whose average daily traded value falls below this many VND.
_LIQUIDITY_WARNING_THRESHOLD = 1_000_000_000


class HoldingValuation(BaseModel):
    """One holding valued at the latest price."""

    symbol: str
    shares: int
    avg_cost: int | None
    wishlist: bool = Field(description="True when shares == 0 (wanted, not owned).")
    latest_price: float | None
    latest_date: date | None
    market_value: float
    weight: float
    source: str | None
    warnings: list[str] = Field(default_factory=list)


class Freshness(BaseModel):
    """Data freshness for the evaluated portfolio."""

    source: str | None = Field(description="Primary provider serving the latest bar.")
    sources: list[str] = Field(default_factory=list)
    latest_date: date | None = None
    stale: bool = False


class PortfolioEvaluationResponse(BaseModel):
    """Valuation, weights, freshness and warnings for the whole portfolio."""

    cash: int
    market_value_total: float
    total_value: float
    cash_weight: float
    market_values: dict[str, float]
    weights: dict[str, float]
    holdings: list[HoldingValuation]
    freshness: Freshness
    warnings: list[str] = Field(default_factory=list)


@router.post("/portfolio/evaluate", response_model=PortfolioEvaluationResponse)
def evaluate_portfolio(
    request: Portfolio,
    service: Annotated[DataService, Depends(get_data_service)],
) -> PortfolioEvaluationResponse:
    """Value the portfolio's holdings at the latest prices.

    Prices prefer the V2 **spot** (raw) closes so a holding values at the actual
    market price of its freshest bar; a ticker without V2 data falls back to the V1
    series. Each holding's latest bar date is compared against the global latest
    session across the whole database, so a ticker that trails the market is flagged
    as stale in its ``Notes``.
    """
    today = service.today
    series_by_symbol = {
        holding.symbol: service.get_prices_preferring_v2_spot(holding.symbol)
        for holding in request.holdings
    }
    latest_prices = {
        symbol: series.rows[-1].close
        for symbol, series in series_by_symbol.items()
        if series.rows
    }
    valuation = portfolio_value_and_weights(request, latest_prices)
    global_latest = service.overall_latest_price_date()

    holdings = [
        _holding_valuation(
            holding, series_by_symbol[holding.symbol], valuation, today, global_latest
        )
        for holding in request.holdings
    ]
    return PortfolioEvaluationResponse(
        cash=request.cash,
        market_value_total=valuation.total_value - valuation.cash_value,
        total_value=valuation.total_value,
        cash_weight=valuation.cash_weight,
        market_values=valuation.market_values,
        weights=valuation.weights,
        holdings=holdings,
        freshness=_freshness(series_by_symbol.values()),
        warnings=_portfolio_warnings(holdings),
    )


def _holding_valuation(
    holding: Holding,
    series: PriceSeries,
    valuation: PortfolioValuation,
    today: date,
    global_latest: date | None,
) -> HoldingValuation:
    """Build the response entry for one holding."""
    rows = series.rows
    latest = rows[-1] if rows else None
    return HoldingValuation(
        symbol=holding.symbol,
        shares=holding.shares,
        avg_cost=holding.avg_cost,
        wishlist=holding.shares == 0,
        latest_price=latest.close if latest is not None else None,
        latest_date=latest.date if latest is not None else None,
        market_value=valuation.market_values[holding.symbol],
        weight=valuation.weights[holding.symbol],
        source=series.source,
        warnings=_holding_warnings(series, rows, today, global_latest),
    )


def _holding_warnings(
    series: PriceSeries,
    rows: list[PriceBar],
    today: date,
    global_latest: date | None,
) -> list[str]:
    """Return human-readable warnings for one holding.

    ``series.warnings`` already carries the "queued for next sync" and "stale"
    messages produced by the data layer; this adds a per-holding missing-price,
    trailing-bar, suspended and illiquid flags.
    """
    warnings = list(series.warnings)
    if not rows:
        warnings.append("missing price: no data available for this ticker")
        return warnings
    latest_date = max(row.date for row in rows)
    if global_latest is not None and latest_date < global_latest:
        warnings.append(f"stale ({latest_date.isoformat()}): bar is behind the latest session")
    if _looks_suspended(rows, today):
        warnings.append(
            "suspended or halted: no price bar for the most recent trading "
            "session (may be a suspension, a long halt or pending data)"
        )
    adv = average_daily_value(_to_daily_bars(rows), _ILLIQUIDITY_SESSIONS)
    if adv <= 0.0:
        warnings.append("illiquid: no traded value reported")
    elif adv < _LIQUIDITY_WARNING_THRESHOLD:
        warnings.append(
            f"low liquidity: average daily traded value {adv:,.0f} VND is below the "
            f"{_LIQUIDITY_WARNING_THRESHOLD:,.0f} VND threshold"
        )
    return warnings


def _to_daily_bars(rows: Iterable[PriceBar]) -> list[DailyBar]:
    """Convert stored price bars into the core's daily-bar view."""
    return [
        DailyBar(
            date=row.date,
            close=row.close,
            adj_close=row.adj_close,
            volume=row.volume,
            value=row.value,
        )
        for row in rows
    ]


def _freshness(series_values: Iterable[PriceSeries]) -> Freshness:
    """Summarise which provider served the data and how fresh it is."""
    series_list = list(series_values)
    sources = sorted({series.source for series in series_list if series.source})
    dated = [(series.rows[-1].date, series.source) for series in series_list if series.rows]
    latest_date = max((day for day, _ in dated), default=None)
    primary = next(
        (source for day, source in dated if source is not None and day == latest_date),
        None,
    )
    return Freshness(
        source=primary or (sources[0] if sources else None),
        sources=sources,
        latest_date=latest_date,
        stale=any(series.stale for series in series_list),
    )


def _portfolio_warnings(holdings: Iterable[HoldingValuation]) -> list[str]:
    """Summarise cross-holding problems the UI can show above the table."""
    items = list(holdings)
    issues: list[str] = []
    missing = [item.symbol for item in items if item.latest_price is None]
    if missing:
        issues.append(f"missing price for {', '.join(missing)}")
    queued = [
        item.symbol
        for item in items
        if any("queued for next sync" in warning for warning in item.warnings)
    ]
    if queued:
        issues.append(f"queued for backfill: {', '.join(queued)}")
    return issues

