"""Unit tests for trading cost models."""

from __future__ import annotations

from decimal import Decimal

from core.costs import commission, round_trip_commission


def test_higher_fee_raises_costs() -> None:
    notional = 100_000_000
    low_fee = commission(notional, Decimal("0.0015"))
    high_fee = commission(notional, Decimal("0.0025"))
    assert high_fee > low_fee


def test_commission_is_fee_times_notional_rounded() -> None:
    assert commission(100_000_000, Decimal("0.0015")) == 150_000


def test_round_trip_is_twice_one_side() -> None:
    notional = 100_000_000
    fee = Decimal("0.0015")
    assert round_trip_commission(notional, fee) == commission(notional, fee) * 2
