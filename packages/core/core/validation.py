"""Shared input validation helpers and bounds for core and API models."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, ValidationError

#: Strict pattern for Vietnamese ticker and index codes (e.g. VNM, HNX1, VN-INDEX).
TICKER_SYMBOL_PATTERN = r"^[A-Z0-9._-]{1,16}$"
TICKER_SYMBOL_RE = re.compile(TICKER_SYMBOL_PATTERN)

#: Earliest historical market date accepted across API and data-sync boundaries.
MIN_MARKET_DATE = date(2000, 1, 1)

#: Maximum number of chunked provider requests allowed for a single date range.
MAX_CHUNKS = 30


def validate_ticker_symbol(value: str, *, field_name: str = "symbol") -> str:
    """Normalize ``value`` and reject malformed or path-like ticker symbols."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    code = value.strip().upper()
    if not code:
        raise ValueError(f"{field_name} must not be empty")
    if ".." in code or code[0] in ".-" or not TICKER_SYMBOL_RE.fullmatch(code):
        raise ValueError(
            f"{field_name} must be 1-16 characters (A-Z, 0-9, ., _, -) without '..'"
        )
    return code


def validate_market_date(value: date, *, field_name: str = "date") -> date:
    """Reject dates earlier than :data:`MIN_MARKET_DATE`."""
    if value < MIN_MARKET_DATE:
        raise ValueError(
            f"{field_name} must not be earlier than {MIN_MARKET_DATE.isoformat()}"
        )
    return value


def validate_finite_float(value: float, *, field_name: str = "value") -> float:
    """Reject NaN and Infinity floating-point inputs."""
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    return value


def format_validation_error(exc: ValidationError) -> str:
    """Format a Pydantic ``ValidationError`` into field path + message only."""
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(segment) for segment in err.get("loc", ()))
        msg = str(err.get("msg", "invalid value"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "invalid parameters"


TickerSymbol = Annotated[str, AfterValidator(validate_ticker_symbol)]
MarketDate = Annotated[date, AfterValidator(validate_market_date)]
FiniteFloat = Annotated[float, AfterValidator(validate_finite_float)]

__all__ = [
    "MAX_CHUNKS",
    "MIN_MARKET_DATE",
    "TICKER_SYMBOL_PATTERN",
    "TICKER_SYMBOL_RE",
    "FiniteFloat",
    "MarketDate",
    "TickerSymbol",
    "format_validation_error",
    "validate_finite_float",
    "validate_market_date",
    "validate_ticker_symbol",
]
