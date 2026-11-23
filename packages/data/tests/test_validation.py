"""Structural validation of provider responses."""

from __future__ import annotations

from datetime import date

import pytest
from support import make_bar

from data.errors import EmptyResultError, SchemaError
from data.validation import canonicalize_price_bars


def test_empty_response_raises() -> None:
    with pytest.raises(EmptyResultError):
        canonicalize_price_bars([], provider="x")


def test_negative_price_raises() -> None:
    with pytest.raises(SchemaError):
        canonicalize_price_bars([make_bar(date(2024, 1, 2), -1.0)], provider="x")


def test_negative_volume_raises() -> None:
    bar = make_bar(date(2024, 1, 2), 10.0, volume=-5)
    with pytest.raises(SchemaError):
        canonicalize_price_bars([bar], provider="x")


def test_sorts_by_date_and_dedupes() -> None:
    later = make_bar(date(2024, 1, 3), 10.0)
    earlier = make_bar(date(2024, 1, 2), 11.0)
    duplicate = make_bar(date(2024, 1, 3), 12.0)
    result = canonicalize_price_bars([later, earlier, duplicate], provider="x")
    assert [bar.date for bar in result] == [date(2024, 1, 2), date(2024, 1, 3)]
    assert result[-1].close == 12.0  # last duplicate wins
