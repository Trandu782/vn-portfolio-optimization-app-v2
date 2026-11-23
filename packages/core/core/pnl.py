"""Profit and loss from holdings, without a trade log.

The user enters what they own (whole shares) and their average cost per share -
the same figure their broker app shows (brokers already adjust it for stock
dividends). From that and the latest close this module computes the cost basis,
market value, unrealized profit or loss in VND and percent, each holding's weight
of the total value and its share of the total P&L, and the "P&L if sold today, net
of costs" figure (the user's brokerage fee plus the 0.1% sell tax).

Assumptions (stated on the P&L page as well):

* prices are the latest close; costs are not part of market value or of the
  unrealized P&L itself, only of the separate net-of-costs figure;
* realized profit, dividends and any transaction history are not tracked;
* a holding with zero shares (a wishlist ticker) is ignored entirely;
* a holding with shares but no average cost (or no price) is listed so the UI can
  prompt for the missing input, but it is excluded from every P&L total and
  counted in ``excluded_count``; its weight still reflects its market value when
  a price exists.

This module is pure: it never touches the network or the database. The caller
supplies the latest prices, the user's fee and the market's sell tax.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from core.costs import commission
from core.portfolio import Portfolio


@dataclass(frozen=True)
class HoldingPnL:
    """One owned holding's market value, cost basis and profit or loss."""

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


@dataclass(frozen=True)
class PnLResult:
    """The per-holding rows and the portfolio totals, including cash."""

    holdings: tuple[HoldingPnL, ...]
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


@dataclass(frozen=True)
class BuyDateComparison:
    """A stock's price return since a buy date next to the benchmark's."""

    stock_return: float
    benchmark_return: float
    beat_market: bool


def _sell_tax_amount(market_value: float, sell_tax: Decimal) -> int:
    """Return the sell tax on ``market_value`` in whole VND, rounded half up."""
    notional = round(market_value)
    return int((Decimal(notional) * sell_tax).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_pnl(
    *,
    portfolio: Portfolio,
    latest_prices: Mapping[str, float],
    brokerage_fee_rate: Decimal,
    sell_tax: Decimal,
) -> PnLResult:
    """Value each owned holding and compute its unrealized profit or loss.

    Args:
        portfolio: The validated holdings and cash balance.
        latest_prices: Most recent close per symbol, in VND. A symbol missing from
            the mapping is reported as a missing price and excluded from totals.
        brokerage_fee_rate: The user's per-side fee as a fraction, from
            ``UserSettings.brokerage_fee_rate``.
        sell_tax: The market's sell-side tax as a fraction, from
            ``core.market_rules.DEFAULT_MARKET_RULES.sell_tax``.

    Returns:
        A :class:`PnLResult`. Market value and ``total_value`` include every owned
        holding and cash; the cost basis, unrealized P&L and net-of-costs totals
        cover only holdings that have both an average cost and a price.

    Notes:
        A holding with zero shares is a wishlist entry and is not part of the P&L
        table. ``pnl_share`` is the holding's unrealized P&L divided by the total
        unrealized P&L and is ``None`` when that total is exactly zero.
    """
    owned = [holding for holding in portfolio.holdings if holding.shares > 0]
    market_values = {
        holding.symbol: (
            float(holding.shares) * latest_prices[holding.symbol]
            if holding.symbol in latest_prices
            else 0.0
        )
        for holding in owned
    }
    cash = float(portfolio.cash)
    market_value_total = sum(market_values.values())
    total_value = cash + market_value_total

    rows: list[HoldingPnL] = []
    cost_basis_total = 0
    unrealized_pnl_total = 0.0
    sell_fee_total = 0
    sell_tax_total = 0
    net_of_costs_total = 0.0
    excluded_count = 0

    for holding in owned:
        price = latest_prices.get(holding.symbol)
        market_value = market_values[holding.symbol]
        weight = market_value / total_value if total_value > 0.0 else 0.0
        avg_cost = holding.avg_cost
        has_cost = avg_cost is not None and avg_cost > 0
        missing_avg_cost = not has_cost
        missing_price = price is None
        cost_basis = holding.shares * avg_cost if avg_cost is not None and avg_cost > 0 else None

        if missing_avg_cost or missing_price:
            excluded_count += 1
            rows.append(
                HoldingPnL(
                    symbol=holding.symbol,
                    shares=holding.shares,
                    avg_cost=holding.avg_cost,
                    buy_date=holding.buy_date,
                    latest_price=price,
                    cost_basis=cost_basis,
                    market_value=market_value,
                    weight=weight,
                    unrealized_pnl=None,
                    unrealized_pnl_pct=None,
                    pnl_share=None,
                    sell_fee=None,
                    sell_tax=None,
                    net_of_costs=None,
                    missing_avg_cost=missing_avg_cost,
                    missing_price=missing_price,
                )
            )
            continue

        assert cost_basis is not None
        unrealized_pnl = market_value - float(cost_basis)
        unrealized_pnl_pct = unrealized_pnl / cost_basis if cost_basis > 0 else None
        sell_fee = commission(round(market_value), brokerage_fee_rate)
        tax = _sell_tax_amount(market_value, sell_tax)
        net_of_costs = unrealized_pnl - sell_fee - tax

        cost_basis_total += cost_basis
        unrealized_pnl_total += unrealized_pnl
        sell_fee_total += sell_fee
        sell_tax_total += tax
        net_of_costs_total += net_of_costs
        rows.append(
            HoldingPnL(
                symbol=holding.symbol,
                shares=holding.shares,
                avg_cost=holding.avg_cost,
                buy_date=holding.buy_date,
                latest_price=price,
                cost_basis=cost_basis,
                market_value=market_value,
                weight=weight,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                pnl_share=None,
                sell_fee=sell_fee,
                sell_tax=tax,
                net_of_costs=net_of_costs,
                missing_avg_cost=False,
                missing_price=False,
            )
        )

    if unrealized_pnl_total != 0.0:
        rows = [
            replace(
                row,
                pnl_share=(
                    row.unrealized_pnl / unrealized_pnl_total
                    if row.unrealized_pnl is not None
                    else None
                ),
            )
            for row in rows
        ]

    unrealized_pnl_pct = (
        unrealized_pnl_total / cost_basis_total if cost_basis_total > 0 else None
    )
    return PnLResult(
        holdings=tuple(rows),
        market_value_total=market_value_total,
        cost_basis_total=cost_basis_total,
        unrealized_pnl_total=unrealized_pnl_total,
        unrealized_pnl_pct=unrealized_pnl_pct,
        sell_fee_total=sell_fee_total,
        sell_tax_total=sell_tax_total,
        net_of_costs_total=net_of_costs_total,
        cash=portfolio.cash,
        total_value=total_value,
        excluded_count=excluded_count,
    )


def compare_buy_return(
    *,
    stock_buy_price: float,
    stock_latest_price: float,
    benchmark_buy_value: float,
    benchmark_latest_value: float,
) -> BuyDateComparison | None:
    """Compare a stock's price return since a buy date with the benchmark's.

    Returns ``None`` when either starting value is not positive, so the caller can
    skip the comparison instead of dividing by zero. ``beat_market`` is true when
    the stock's return is at least the benchmark's.
    """
    if stock_buy_price <= 0.0 or benchmark_buy_value <= 0.0:
        return None
    stock_return = stock_latest_price / stock_buy_price - 1.0
    benchmark_return = benchmark_latest_value / benchmark_buy_value - 1.0
    return BuyDateComparison(
        stock_return=stock_return,
        benchmark_return=benchmark_return,
        beat_market=stock_return >= benchmark_return,
    )


def first_close_on_or_after(rows: Sequence[tuple[date, float]], day: date) -> float | None:
    """Return the close of the first bar dated on or after ``day`` (or ``None``).

    The buy date is user-supplied and may fall on a weekend or holiday, so the
    first trading day on or after it is the natural reference price. ``rows`` must
    be sorted by date ascending.
    """
    for bar_date, close in rows:
        if bar_date >= day:
            return float(close)
    return None


__all__ = [
    "BuyDateComparison",
    "HoldingPnL",
    "PnLResult",
    "compare_buy_return",
    "compute_pnl",
    "first_close_on_or_after",
]
