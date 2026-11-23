"""Hand-computed tests for ``core.pnl``.

Every number is worked out by hand in the test so a regression in the cost basis,
market value, P&L, net-of-costs or buy-date comparison shows up as a mismatch.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.pnl import compare_buy_return, compute_pnl, first_close_on_or_after
from core.portfolio import Holding, Portfolio

FEE = Decimal("0.0015")
SELL_TAX = Decimal("0.001")


def _portfolio(*holdings: Holding, cash: int = 0) -> Portfolio:
    """Build a portfolio from holdings and a cash balance."""
    return Portfolio(holdings=list(holdings), cash=cash)


def test_hand_computed_pnl() -> None:
    portfolio = _portfolio(
        Holding(symbol="VNM", shares=100, avg_cost=40_000),
        Holding(symbol="FPT", shares=200, avg_cost=60_000),
        cash=5_000_000,
    )
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices={"VNM": 50_000.0, "FPT": 80_000.0},
        brokerage_fee_rate=FEE,
        sell_tax=SELL_TAX,
    )

    rows = {row.symbol: row for row in result.holdings}
    assert rows["VNM"].cost_basis == 4_000_000
    assert rows["VNM"].market_value == pytest.approx(5_000_000.0)
    assert rows["VNM"].unrealized_pnl == pytest.approx(1_000_000.0)
    assert rows["VNM"].unrealized_pnl_pct == pytest.approx(0.25)
    assert rows["VNM"].weight == pytest.approx(5_000_000.0 / 26_000_000.0)
    assert rows["VNM"].pnl_share == pytest.approx(0.2)

    assert rows["FPT"].cost_basis == 12_000_000
    assert rows["FPT"].market_value == pytest.approx(16_000_000.0)
    assert rows["FPT"].unrealized_pnl == pytest.approx(4_000_000.0)
    assert rows["FPT"].unrealized_pnl_pct == pytest.approx(1.0 / 3.0)
    assert rows["FPT"].weight == pytest.approx(16_000_000.0 / 26_000_000.0)
    assert rows["FPT"].pnl_share == pytest.approx(0.8)

    assert result.market_value_total == pytest.approx(21_000_000.0)
    assert result.cost_basis_total == 16_000_000
    assert result.unrealized_pnl_total == pytest.approx(5_000_000.0)
    assert result.unrealized_pnl_pct == pytest.approx(5_000_000.0 / 16_000_000.0)
    assert result.cash == 5_000_000
    assert result.total_value == pytest.approx(26_000_000.0)
    assert result.excluded_count == 0


def test_net_of_costs_uses_fee_and_sell_tax() -> None:
    portfolio = _portfolio(
        Holding(symbol="VNM", shares=100, avg_cost=40_000),
        Holding(symbol="FPT", shares=200, avg_cost=60_000),
    )
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices={"VNM": 50_000.0, "FPT": 80_000.0},
        brokerage_fee_rate=FEE,
        sell_tax=SELL_TAX,
    )

    rows = {row.symbol: row for row in result.holdings}
    # VNM: 5,000,000 * 0.15% = 7,500 fee; 5,000,000 * 0.1% = 5,000 tax.
    assert rows["VNM"].sell_fee == 7_500
    assert rows["VNM"].sell_tax == 5_000
    assert rows["VNM"].net_of_costs == pytest.approx(987_500.0)
    # FPT: 16,000,000 * 0.15% = 24,000 fee; 16,000,000 * 0.1% = 16,000 tax.
    assert rows["FPT"].sell_fee == 24_000
    assert rows["FPT"].sell_tax == 16_000
    assert rows["FPT"].net_of_costs == pytest.approx(3_960_000.0)

    assert result.sell_fee_total == 31_500
    assert result.sell_tax_total == 21_000
    assert result.net_of_costs_total == pytest.approx(4_947_500.0)


def test_missing_avg_cost_is_listed_but_excluded() -> None:
    portfolio = _portfolio(
        Holding(symbol="VNM", shares=100),
        Holding(symbol="FPT", shares=200, avg_cost=60_000),
    )
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices={"VNM": 50_000.0, "FPT": 80_000.0},
        brokerage_fee_rate=FEE,
        sell_tax=SELL_TAX,
    )

    rows = {row.symbol: row for row in result.holdings}
    assert rows["VNM"].missing_avg_cost is True
    assert rows["VNM"].unrealized_pnl is None
    assert rows["VNM"].net_of_costs is None
    assert rows["VNM"].market_value == pytest.approx(5_000_000.0)
    assert rows["FPT"].missing_avg_cost is False

    assert result.excluded_count == 1
    assert result.cost_basis_total == 12_000_000
    assert result.unrealized_pnl_total == pytest.approx(4_000_000.0)
    # VNM's market value still counts towards the portfolio total and its weight.
    assert result.market_value_total == pytest.approx(21_000_000.0)


def test_missing_price_is_excluded() -> None:
    portfolio = _portfolio(Holding(symbol="VNM", shares=100, avg_cost=40_000))
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices={},
        brokerage_fee_rate=FEE,
        sell_tax=SELL_TAX,
    )

    [row] = result.holdings
    assert row.missing_price is True
    assert row.latest_price is None
    assert row.unrealized_pnl is None
    assert result.excluded_count == 1
    assert result.market_value_total == pytest.approx(0.0)
    assert result.total_value == pytest.approx(0.0)


def test_wishlist_holding_is_ignored() -> None:
    portfolio = _portfolio(
        Holding(symbol="VNM", shares=0),
        Holding(symbol="FPT", shares=100, avg_cost=50_000),
    )
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices={"VNM": 50_000.0, "FPT": 60_000.0},
        brokerage_fee_rate=FEE,
        sell_tax=SELL_TAX,
    )

    assert [row.symbol for row in result.holdings] == ["FPT"]
    assert result.excluded_count == 0
    assert result.market_value_total == pytest.approx(6_000_000.0)


def test_buy_date_is_copied_to_the_row() -> None:
    bought = date(2023, 1, 5)
    portfolio = _portfolio(
        Holding(symbol="VNM", shares=100, avg_cost=40_000, buy_date=bought)
    )
    result = compute_pnl(
        portfolio=portfolio,
        latest_prices={"VNM": 50_000.0},
        brokerage_fee_rate=FEE,
        sell_tax=SELL_TAX,
    )

    [row] = result.holdings
    assert row.buy_date == bought


def test_compare_buy_return_marks_the_winner() -> None:
    # Stock 100 -> 120 (+20%) vs VN-Index 1000 -> 1100 (+10%): it beat the market.
    win = compare_buy_return(
        stock_buy_price=100.0,
        stock_latest_price=120.0,
        benchmark_buy_value=1000.0,
        benchmark_latest_value=1100.0,
    )
    assert win is not None
    assert win.stock_return == pytest.approx(0.20)
    assert win.benchmark_return == pytest.approx(0.10)
    assert win.beat_market is True

    # Stock 100 -> 105 (+5%) vs +10%: it lagged the market.
    lag = compare_buy_return(
        stock_buy_price=100.0,
        stock_latest_price=105.0,
        benchmark_buy_value=1000.0,
        benchmark_latest_value=1100.0,
    )
    assert lag is not None
    assert lag.beat_market is False

    assert (
        compare_buy_return(
            stock_buy_price=0.0,
            stock_latest_price=120.0,
            benchmark_buy_value=1000.0,
            benchmark_latest_value=1100.0,
        )
        is None
    )


def test_first_close_on_or_after_handles_weekends_and_gaps() -> None:
    rows = [
        (date(2024, 1, 5), 40_000.0),
        (date(2024, 1, 8), 41_000.0),
    ]
    # A Saturday buy date falls back to the next trading day (Monday).
    assert first_close_on_or_after(rows, date(2024, 1, 6)) == pytest.approx(41_000.0)
    assert first_close_on_or_after(rows, date(2024, 1, 8)) == pytest.approx(41_000.0)
    assert first_close_on_or_after(rows, date(2024, 1, 9)) is None
