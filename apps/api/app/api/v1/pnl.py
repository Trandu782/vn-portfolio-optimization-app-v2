"""Profit and loss route: value holdings from average cost alone.

``POST /pnl/evaluate`` takes the same holdings as the portfolio page (symbol,
whole shares, optional average cost and buy date, plus cash), values them at the
latest close and returns the cost basis, market value, unrealized P&L in VND and
percent, each holding's weight and share of the total P&L, and the "P&L if sold
today, net of costs" figure using the user's brokerage fee and the 0.1% sell tax.
Holdings with a buy date are additionally compared with VN-Index over the same
period.

The route is thin. Validation lives in ``core.portfolio``, the P&L maths in
``core.pnl`` and the price lookups in the data layer. No trade log is involved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.api.v1.data import get_data_service
from app.api.v1.schemas import Assumptions, assumptions_from
from core.market_rules import DEFAULT_MARKET_RULES
from core.pnl import (
    BuyDateComparison,
    compare_buy_return,
    compute_pnl,
    first_close_on_or_after,
)
from core.portfolio import Holding, Portfolio
from core.settings import UserSettings
from data.models import PriceBar, PriceSeries
from data.service import DataService

router = APIRouter(tags=["pnl"])

#: Benchmark used for the "beat the market?" comparison on the P&L page.
BENCHMARK = "VNINDEX"


class PnLRequest(BaseModel):
    """Holdings, cash and the user settings that drive the cost estimate."""

    holdings: list[Holding] = Field(
        default_factory=list,
        description="Holdings (with optional average cost and buy date).",
    )
    cash: int = Field(default=0, ge=0, description="Cash balance in whole VND.")
    settings: UserSettings | None = Field(
        default=None,
        description="User settings (brokerage fee). Defaults apply when omitted.",
    )


class HoldingPnLResponse(BaseModel):
    """One holding's market value, cost basis, P&L and buy-date comparison."""

    symbol: str
    shares: int
    avg_cost: int | None
    buy_date: date | None
    latest_price: float | None
    cost_basis: int | None
    market_value: float
    weight: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    pnl_share: float | None
    sell_fee: int | None
    sell_tax: int | None
    net_of_costs: float | None
    missing_avg_cost: bool
    missing_price: bool
    buy_price: float | None = None
    price_return: float | None = None
    benchmark_return: float | None = None
    beat_market: bool | None = None


class PnLSummary(BaseModel):
    """The headline figures shown as cards above the P&L table."""

    market_value_total: float
    cost_basis_total: int
    unrealized_pnl_total: float
    unrealized_pnl_pct: float | None
    sell_fee_total: int
    sell_tax_total: int
    net_of_costs_total: float
    cash: int
    total_value: float
    excluded_count: int


class PnLResponse(BaseModel):
    """Per-holding rows and totals, with the settings and market rules used."""

    summary: PnLSummary
    holdings: list[HoldingPnLResponse]
    assumptions: Assumptions
    sell_tax: float
    warnings: list[str] = Field(default_factory=list)


@router.post("/pnl/evaluate", response_model=PnLResponse)
def evaluate_pnl(
    request: PnLRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> PnLResponse:
    """Value each holding at the latest close and report unrealized P&L."""
    try:
        portfolio = Portfolio(holdings=request.holdings, cash=request.cash)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings = request.settings or UserSettings()
    series_by_symbol = {
        holding.symbol: service.get_prices(holding.symbol, ensure=True)
        for holding in portfolio.holdings
    }
    latest_prices = {
        symbol: series.rows[-1].close
        for symbol, series in series_by_symbol.items()
        if series.rows
    }
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices=latest_prices,
        brokerage_fee_rate=settings.brokerage_fee_rate,
        sell_tax=DEFAULT_MARKET_RULES.sell_tax,
    )
    comparisons = _buy_date_comparisons(service, portfolio, series_by_symbol)
    holdings_by_symbol = {holding.symbol: holding for holding in portfolio.holdings}

    warnings: list[str] = []
    rows: list[HoldingPnLResponse] = []
    for row in result.holdings:
        held = holdings_by_symbol.get(row.symbol)
        comparison = comparisons.get(row.symbol)
        if row.missing_avg_cost:
            warnings.append(
                f"{row.symbol}: enter your average cost to include it in the P&L totals"
            )
        if row.missing_price:
            warnings.append(f"{row.symbol}: no price available; excluded from the P&L totals")
        if held is not None and held.buy_date is not None and comparison is None:
            warnings.append(
                f"{row.symbol}: not enough price history to compare with VN-Index "
                f"since {held.buy_date.isoformat()}"
            )
        series = series_by_symbol.get(row.symbol)
        if series is not None:
            warnings.extend(f"{row.symbol}: {warning}" for warning in series.warnings)

        buy_price: float | None = None
        buy_comparison: BuyDateComparison | None = None
        if comparison is not None:
            buy_price, buy_comparison = comparison
        rows.append(
            HoldingPnLResponse(
                symbol=row.symbol,
                shares=row.shares,
                avg_cost=row.avg_cost,
                buy_date=row.buy_date,
                latest_price=row.latest_price,
                cost_basis=row.cost_basis,
                market_value=row.market_value,
                weight=row.weight,
                unrealized_pnl=row.unrealized_pnl,
                unrealized_pnl_pct=row.unrealized_pnl_pct,
                pnl_share=row.pnl_share,
                sell_fee=row.sell_fee,
                sell_tax=row.sell_tax,
                net_of_costs=row.net_of_costs,
                missing_avg_cost=row.missing_avg_cost,
                missing_price=row.missing_price,
                buy_price=buy_price,
                price_return=buy_comparison.stock_return if buy_comparison else None,
                benchmark_return=buy_comparison.benchmark_return if buy_comparison else None,
                beat_market=buy_comparison.beat_market if buy_comparison else None,
            )
        )

    return PnLResponse(
        summary=PnLSummary(
            market_value_total=result.market_value_total,
            cost_basis_total=result.cost_basis_total,
            unrealized_pnl_total=result.unrealized_pnl_total,
            unrealized_pnl_pct=result.unrealized_pnl_pct,
            sell_fee_total=result.sell_fee_total,
            sell_tax_total=result.sell_tax_total,
            net_of_costs_total=result.net_of_costs_total,
            cash=result.cash,
            total_value=result.total_value,
            excluded_count=result.excluded_count,
        ),
        holdings=rows,
        assumptions=assumptions_from(settings),
        sell_tax=float(DEFAULT_MARKET_RULES.sell_tax),
        warnings=list(dict.fromkeys(warnings)),
    )


def _buy_date_comparisons(
    service: DataService,
    portfolio: Portfolio,
    series_by_symbol: Mapping[str, PriceSeries],
) -> dict[str, tuple[float, BuyDateComparison]]:
    """Compare each dated, owned holding's price return with VN-Index."""
    dated = [
        holding
        for holding in portfolio.holdings
        if holding.buy_date is not None and holding.shares > 0
    ]
    if not dated:
        return {}
    earliest = min(holding.buy_date for holding in dated if holding.buy_date is not None)
    index_series = service.get_index_prices(BENCHMARK, start=earliest, end=service.today)
    index_rows = index_series.rows
    if not index_rows:
        return {}
    index_latest = index_rows[-1].close
    comparisons: dict[str, tuple[float, BuyDateComparison]] = {}
    for holding in dated:
        assert holding.buy_date is not None
        series = series_by_symbol.get(holding.symbol)
        if series is None or not series.rows:
            continue
        stock_buy = _first_close(series.rows, holding.buy_date)
        index_buy = _first_close(index_rows, holding.buy_date)
        if stock_buy is None or index_buy is None:
            continue
        comparison = compare_buy_return(
            stock_buy_price=stock_buy,
            stock_latest_price=series.rows[-1].close,
            benchmark_buy_value=index_buy,
            benchmark_latest_value=index_latest,
        )
        if comparison is not None:
            comparisons[holding.symbol] = (stock_buy, comparison)
    return comparisons


def _first_close(rows: Sequence[PriceBar], day: date) -> float | None:
    """Return the close of the first bar on or after ``day`` (bars stay sorted)."""
    return first_close_on_or_after([(row.date, row.close) for row in rows], day)
