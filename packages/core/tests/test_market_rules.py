"""Unit tests for the market rules configuration."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.market_rules import DEFAULT_MARKET_RULES, ExchangeRules, MarketRules


def test_lot_size_is_100_on_every_exchange() -> None:
    assert {rules.lot_size for rules in DEFAULT_MARKET_RULES.exchanges.values()} == {100}


def test_sell_tax_is_point_one_percent() -> None:
    assert DEFAULT_MARKET_RULES.sell_tax == Decimal("0.001")


def test_daily_price_limits_per_exchange() -> None:
    limits = {
        code: rules.daily_price_limit for code, rules in DEFAULT_MARKET_RULES.exchanges.items()
    }
    assert limits == {
        "HOSE": Decimal("0.07"),
        "HNX": Decimal("0.10"),
        "UPCoM": Decimal("0.15"),
    }


def test_trading_holidays_are_dates() -> None:
    holidays = DEFAULT_MARKET_RULES.trading_holidays
    assert holidays, "expected a non-empty illustrative holiday set"
    assert all(isinstance(day, date) for day in holidays)


def test_market_rules_are_immutable_values() -> None:
    rules = DEFAULT_MARKET_RULES.exchanges["HOSE"]
    assert isinstance(DEFAULT_MARKET_RULES, MarketRules)
    assert rules == ExchangeRules(code="HOSE", lot_size=100, daily_price_limit=Decimal("0.07"))
