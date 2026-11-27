"""User portfolio: validated holdings, cash and pure valuation math.

A :class:`Holding` is a whole-number share count for one ticker (optionally with
an average cost) and a :class:`Portfolio` bundles holdings with a cash balance.
A holding with zero shares is a *wishlist* entry: a ticker the user wants
considered but does not own yet, so it appears in the weights table with zero
value and still feeds the universe and the optimizer.

This module is pure domain logic. It validates structure (unique symbols, whole
share counts, non-negative VND amounts) and values holdings from already-fetched
prices. It never touches the network or the database, so "known symbol" checks
and on-demand backfill live in the API/data layer. Average cost and an optional
buy date are stored for the P&L page, which lives in ``core.pnl``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.validation import validate_market_date, validate_ticker_symbol


class Holding(BaseModel):
    """One portfolio line: a ticker, a whole share count and an optional average cost."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Ticker code; normalised to upper case.")
    shares: int = Field(
        ..., ge=0, description="Whole number of shares held (0 means a wishlist ticker)."
    )
    avg_cost: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional average cost per share in whole VND, as shown in the broker app "
            "(brokers already adjust it for stock dividends). Feeds the P&L page."
        ),
    )
    buy_date: date | None = Field(
        default=None,
        description=(
            "Optional ISO date the holding was bought. When present, the P&L page "
            "compares the stock's price return since then with VN-Index."
        ),
    )

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        """Trim, upper-case and validate the ticker symbol."""
        return validate_ticker_symbol(value, field_name="symbol")

    @field_validator("buy_date")
    @classmethod
    def _validate_buy_date(cls, value: date | None) -> date | None:
        """Reject buy dates earlier than MIN_MARKET_DATE."""
        if value is not None:
            return validate_market_date(value, field_name="buy_date")
        return None

    @field_validator("shares", "avg_cost", mode="before")
    @classmethod
    def _require_whole_amount(cls, value: Any) -> Any:
        """Reject fractional share counts and VND amounts with a clear message."""
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("shares and avg_cost must be whole numbers")
        return value


class Portfolio(BaseModel):
    """A set of holdings plus a cash balance (all VND amounts as whole integers)."""

    model_config = ConfigDict(frozen=True)

    holdings: list[Holding] = Field(
        default_factory=list,
        max_length=200,
        description="One entry per ticker; symbols must be unique.",
    )
    cash: int = Field(default=0, ge=0, description="Cash balance in whole VND.")

    @model_validator(mode="after")
    def _unique_symbols(self) -> Self:
        """Reject duplicate tickers with a message naming every offender."""
        seen: set[str] = set()
        duplicates: list[str] = []
        for holding in self.holdings:
            if holding.symbol in seen:
                duplicates.append(holding.symbol)
            seen.add(holding.symbol)
        if duplicates:
            names = ", ".join(sorted(set(duplicates)))
            raise ValueError(f"duplicate symbol(s) in portfolio holdings: {names}")
        return self

    @property
    def symbols(self) -> list[str]:
        """Return the holding symbols in portfolio order."""
        return [holding.symbol for holding in self.holdings]


@dataclass(frozen=True)
class PortfolioValuation:
    """Market values, weights and totals for a portfolio at the latest prices."""

    market_values: dict[str, float]
    """Market value per symbol in VND (0 for a missing price or a wishlist entry)."""

    total_value: float
    """Total portfolio value in VND, including cash."""

    cash_value: float
    """Cash balance in VND (the same value as ``Portfolio.cash``, as a float)."""

    weights: dict[str, float]
    """Weight of each holding as a fraction of ``total_value``."""

    cash_weight: float
    """Cash weight as a fraction of ``total_value``."""


def portfolio_value_and_weights(
    portfolio: Portfolio, latest_prices: Mapping[str, float]
) -> PortfolioValuation:
    """Value each holding and compute its weight of the total portfolio value.

    Args:
        portfolio: The validated portfolio (holdings + cash).
        latest_prices: Most recent close per symbol, in VND. A symbol missing from
            the mapping contributes zero market value; the caller reports it as a
            missing price.

    Returns:
        A :class:`PortfolioValuation`. ``total_value`` includes cash. ``weights``
        and ``cash_weight`` are fractions of ``total_value`` and sum to one when
        the portfolio has any value; every weight is ``0.0`` when it does not.

    Notes:
        A holding with zero shares (a wishlist ticker) always has a zero market
        value and weight but is still present in ``market_values`` and ``weights``.
        Average cost and buy date are ignored here: they feed the separate P&L
        calculation in ``core.pnl``.
    """
    market_values: dict[str, float] = {}
    for holding in portfolio.holdings:
        price = latest_prices.get(holding.symbol)
        market_values[holding.symbol] = (
            float(holding.shares) * price if price is not None else 0.0
        )

    cash_value = float(portfolio.cash)
    total_value = cash_value + sum(market_values.values())
    if total_value > 0.0:
        weights = {symbol: value / total_value for symbol, value in market_values.items()}
        cash_weight = cash_value / total_value
    else:
        weights = dict.fromkeys(market_values, 0.0)
        cash_weight = 0.0
    return PortfolioValuation(
        market_values=market_values,
        total_value=total_value,
        cash_value=cash_value,
        weights=weights,
        cash_weight=cash_weight,
    )
