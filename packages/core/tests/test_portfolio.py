"""Unit tests for holdings, portfolio validation and valuation math."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.portfolio import Holding, Portfolio, portfolio_value_and_weights

# -- validation ----------------------------------------------------------------


def test_holding_normalises_symbol_and_defaults_avg_cost() -> None:
    holding = Holding(symbol="  vnm ", shares=100)
    assert holding.symbol == "VNM"
    assert holding.avg_cost is None


def test_holding_rejects_empty_symbol() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Holding(symbol="   ", shares=1)
    assert "symbol must not be empty" in str(exc_info.value)


def test_holding_rejects_negative_shares() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Holding(symbol="VNM", shares=-1)
    assert "greater than or equal to 0" in str(exc_info.value)


def test_holding_rejects_fractional_shares() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Holding(symbol="VNM", shares=1.5)
    assert "whole numbers" in str(exc_info.value)


def test_holding_accepts_optional_avg_cost() -> None:
    holding = Holding(symbol="VNM", shares=100, avg_cost=50_000)
    assert holding.avg_cost == 50_000


def test_holding_rejects_negative_avg_cost() -> None:
    with pytest.raises(ValidationError):
        Holding(symbol="VNM", shares=100, avg_cost=-1)


def test_portfolio_defaults_to_empty_and_zero_cash() -> None:
    portfolio = Portfolio()
    assert portfolio.holdings == []
    assert portfolio.cash == 0
    assert portfolio.symbols == []


def test_portfolio_rejects_duplicate_symbols_case_insensitively() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Portfolio(
            holdings=[
                Holding(symbol="vnm", shares=100),
                Holding(symbol=" VNM ", shares=50),
            ]
        )
    message = str(exc_info.value).lower()
    assert "duplicate" in message
    assert "vnm" in message


def test_portfolio_rejects_negative_cash() -> None:
    with pytest.raises(ValidationError):
        Portfolio(cash=-1)


def test_portfolio_allows_mixed_case_unique_symbols() -> None:
    portfolio = Portfolio(
        holdings=[Holding(symbol="vnm", shares=1), Holding(symbol="fpt", shares=2)]
    )
    assert portfolio.symbols == ["VNM", "FPT"]


# -- valuation -----------------------------------------------------------------


def test_value_and_weights_include_cash() -> None:
    portfolio = Portfolio(
        holdings=[
            Holding(symbol="VNM", shares=100, avg_cost=40_000),
            Holding(symbol="FPT", shares=200, avg_cost=60_000),
        ],
        cash=5_000_000,
    )

    valuation = portfolio_value_and_weights(portfolio, {"VNM": 50_000, "FPT": 100_000})

    assert valuation.market_values == {"VNM": 5_000_000.0, "FPT": 20_000_000.0}
    assert valuation.cash_value == 5_000_000.0
    assert valuation.total_value == 30_000_000.0
    assert valuation.weights["VNM"] == pytest.approx(5 / 30)
    assert valuation.weights["FPT"] == pytest.approx(20 / 30)
    assert valuation.cash_weight == pytest.approx(5 / 30)
    assert sum(valuation.weights.values()) + valuation.cash_weight == pytest.approx(1.0)


def test_missing_price_contributes_zero_value() -> None:
    portfolio = Portfolio(
        holdings=[Holding(symbol="VNM", shares=100), Holding(symbol="XYZ", shares=10)]
    )

    valuation = portfolio_value_and_weights(portfolio, {"VNM": 50_000})

    assert valuation.market_values["XYZ"] == 0.0
    assert valuation.weights["XYZ"] == 0.0
    assert valuation.total_value == 5_000_000.0


def test_wishlist_holding_has_zero_value_and_weight() -> None:
    portfolio = Portfolio(
        holdings=[Holding(symbol="VNM", shares=100), Holding(symbol="FPT", shares=0)],
        cash=0,
    )

    valuation = portfolio_value_and_weights(portfolio, {"VNM": 50_000, "FPT": 100_000})

    assert valuation.market_values["FPT"] == 0.0
    assert valuation.weights["FPT"] == 0.0
    assert "FPT" in valuation.weights
    assert valuation.total_value == 5_000_000.0


def test_cash_only_portfolio_is_all_cash() -> None:
    portfolio = Portfolio(cash=1_000_000)

    valuation = portfolio_value_and_weights(portfolio, {})

    assert valuation.total_value == 1_000_000.0
    assert valuation.cash_weight == 1.0
    assert valuation.weights == {}


def test_zero_value_portfolio_has_zero_weights() -> None:
    portfolio = Portfolio(holdings=[Holding(symbol="VNM", shares=0)], cash=0)

    valuation = portfolio_value_and_weights(portfolio, {"VNM": 50_000})

    assert valuation.total_value == 0.0
    assert valuation.weights["VNM"] == 0.0
    assert valuation.cash_weight == 0.0
