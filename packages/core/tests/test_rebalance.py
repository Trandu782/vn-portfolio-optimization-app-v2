"""Unit tests for the rebalance engine, cost model and policies.

The network is never touched: every test builds a portfolio and prices by hand and
calls the pure engine directly.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from core.market_rules import DEFAULT_MARKET_RULES
from core.portfolio import Holding, Portfolio
from core.rebalance import (
    RebalanceContext,
    RebalanceDecision,
    RebalanceResult,
    build_cost_model,
    build_rebalance_policy,
    cost_models,
    rebalance,
    rebalance_policies,
)

FEE = Decimal("0.0015")
SELL_TAX = Decimal("0.001")


def _portfolio(holdings: list[tuple[str, int]], cash: int = 0) -> Portfolio:
    """Build a portfolio from ``(symbol, shares)`` pairs and a cash balance."""
    return Portfolio(
        holdings=[Holding(symbol=symbol, shares=shares) for symbol, shares in holdings],
        cash=cash,
    )


def _run(
    portfolio: Portfolio,
    prices: dict[str, float],
    targets: dict[str, float],
    *,
    policy: str = "full",
    policy_params: dict[str, Any] | None = None,
    min_notional: int = 1_000_000,
) -> RebalanceResult:
    """Run the engine with the test fee and HOSE lot sizes."""
    return rebalance(
        portfolio=portfolio,
        prices=prices,
        target_weights=targets,
        exchanges=dict.fromkeys(prices, "HOSE"),
        brokerage_fee_rate=FEE,
        policy=policy,
        policy_params=policy_params,
        min_notional=min_notional,
    )


def test_vn_cost_model_charges_fee_on_both_sides_and_tax_on_sells() -> None:
    model = build_cost_model("vn", brokerage_fee_rate=FEE, sell_tax=SELL_TAX)
    buy = model.estimate(10_000_000, "buy")
    sell = model.estimate(10_000_000, "sell")

    assert (buy.fee, buy.tax) == (15_000, 0)
    assert (sell.fee, sell.tax) == (15_000, 10_000)
    assert sell.total == 25_000


def test_builtin_registries_are_populated() -> None:
    assert "vn" in cost_models.list()
    assert {"full", "threshold_band"} <= set(rebalance_policies.list())


def test_unknown_ids_raise_key_error() -> None:
    with pytest.raises(KeyError):
        build_cost_model("does-not-exist", brokerage_fee_rate=FEE, sell_tax=SELL_TAX)
    with pytest.raises(KeyError):
        build_rebalance_policy("does-not-exist")


def test_full_rebalance_sells_before_buys_with_cost_math() -> None:
    portfolio = _portfolio([("VNM", 1000), ("FPT", 200)], cash=30_000_000)
    prices = {"VNM": 50_000.0, "FPT": 100_000.0}

    result = _run(portfolio, prices, {"VNM": 0.3, "FPT": 0.5})

    assert result.total_value == pytest.approx(100_000_000.0)
    assert result.cash_weight == pytest.approx(0.3)
    assert result.target_cash_weight == pytest.approx(0.2)

    assert [order.side for order in result.orders] == ["sell", "buy"]
    sell, buy = result.orders
    assert (sell.symbol, sell.lots, sell.shares, sell.value) == ("VNM", 4, 400, 20_000_000)
    assert (sell.fee, sell.tax) == (30_000, 20_000)
    assert (buy.symbol, buy.lots, buy.shares, buy.value) == ("FPT", 3, 300, 30_000_000)
    assert (buy.fee, buy.tax) == (45_000, 0)

    assert result.total_fee == 75_000
    assert result.total_tax == 20_000
    assert result.total_cost == 95_000
    assert result.turnover == 50_000_000
    assert result.residual_cash == 19_905_000

    positions = {item.symbol: item for item in result.positions}
    assert positions["VNM"].current_weight == pytest.approx(0.5)
    assert positions["VNM"].target_weight == pytest.approx(0.3)
    assert positions["FPT"].current_weight == pytest.approx(0.2)
    assert positions["FPT"].target_weight == pytest.approx(0.5)


def test_never_sells_more_than_held_and_rounds_to_lots() -> None:
    # 250 shares is not a whole number of 100-share lots, so a full exit sells 200.
    portfolio = _portfolio([("VNM", 250)])
    result = _run(portfolio, {"VNM": 50_000.0}, {"VNM": 0.0})

    [order] = result.orders
    assert order.side == "sell"
    assert order.shares == 200
    assert order.shares <= 250
    assert order.lots == 2
    assert order.shares % 100 == 0


def test_buy_rounds_down_to_whole_lots() -> None:
    portfolio = _portfolio([], cash=30_000_000)
    result = _run(portfolio, {"AAA": 45_000.0}, {"AAA": 1.0})

    [order] = result.orders
    assert order.side == "buy"
    assert order.lots == 6
    assert order.shares == 600  # 30,000,000 / 45,000 = 666.7 shares -> 6 lots
    assert order.value == 27_000_000


def test_orders_below_min_notional_are_skipped() -> None:
    portfolio = _portfolio([], cash=10_000_000)
    result = _run(
        portfolio,
        {"AAA": 10_000.0},
        {"AAA": 0.5},
        min_notional=6_000_000,
    )

    assert result.orders == ()
    assert any("below the minimum" in warning for warning in result.warnings)


def test_buys_are_funded_and_residual_cash_stays_non_negative() -> None:
    # The sell of 150 shares rounds to one lot, so the buy must shrink to fit cash.
    portfolio = _portfolio([("AAA", 150)])
    result = rebalance(
        portfolio=portfolio,
        prices={"AAA": 100.0, "BBB": 60.0},
        target_weights={"BBB": 1.0},
        exchanges={"AAA": "HOSE", "BBB": "HOSE"},
        brokerage_fee_rate=Decimal("0"),
        min_notional=0,
    )

    assert result.residual_cash >= 0
    [buy] = [order for order in result.orders if order.side == "buy"]
    assert buy.shares == 100  # one lot fits the sell proceeds less the 10 VND sell tax
    assert result.residual_cash == 3_990


def test_threshold_band_skips_small_drifts() -> None:
    portfolio = _portfolio([("AAA", 500), ("BBB", 500)])
    prices = {"AAA": 100_000.0, "BBB": 100_000.0}

    result = _run(
        portfolio,
        prices,
        {"AAA": 0.52, "BBB": 0.48},
        policy="threshold_band",
        policy_params={"band": 0.05},
    )

    assert result.orders == ()
    positions = {item.symbol: item for item in result.positions}
    assert positions["AAA"].target_weight == pytest.approx(0.5)
    assert positions["BBB"].target_weight == pytest.approx(0.5)


def test_threshold_band_scales_trades_to_the_turnover_cap() -> None:
    portfolio = _portfolio([("AAA", 500), ("BBB", 500)])
    prices = {"AAA": 100_000.0, "BBB": 100_000.0}

    # Zero costs so the sell proceeds fund the scaled-down buy exactly.
    result = rebalance(
        portfolio=portfolio,
        prices=prices,
        target_weights={"AAA": 0.7, "BBB": 0.3},
        exchanges=dict.fromkeys(prices, "HOSE"),
        brokerage_fee_rate=Decimal("0"),
        market_rules=replace(DEFAULT_MARKET_RULES, sell_tax=Decimal("0")),
        policy="threshold_band",
        policy_params={"band": 0.0, "turnover_cap": 0.2},
    )

    positions = {item.symbol: item for item in result.positions}
    # Gross delta 0.2 + 0.2 = 0.4 is capped at 0.2, so every delta is halved.
    assert positions["AAA"].target_weight == pytest.approx(0.6)
    assert positions["BBB"].target_weight == pytest.approx(0.4)
    assert [order.side for order in result.orders] == ["sell", "buy"]
    assert result.turnover == 20_000_000


def test_a_new_policy_is_one_registration() -> None:
    """Acceptance: a new policy is one class plus one registration."""

    class _NoParams(BaseModel):
        pass

    @rebalance_policies.register(
        id="test_hold_current",
        name="Test hold current",
        description="Test-only policy that leaves every symbol at its current weight.",
        parameter_schema=_NoParams,
    )
    class HoldCurrent:
        id = "test_hold_current"

        def __init__(self, params: dict[str, object] | None = None) -> None:
            _NoParams(**(params or {}))

        def decide(self, context: RebalanceContext) -> RebalanceDecision:
            return RebalanceDecision(effective_targets=dict(context.current_weights))

    portfolio = _portfolio([("AAA", 500)])
    result = _run(
        portfolio,
        {"AAA": 100_000.0},
        {"AAA": 0.0},
        policy="test_hold_current",
    )
    assert result.orders == ()
