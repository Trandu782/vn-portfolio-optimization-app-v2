"""DNSE V2 OHLCV adapter (fallback).

Endpoint shape from the V1 adapter: ``GET /dnse-financial-products/v1/price-history``
with ``symbol``/``resolution=D``/``from``/``to`` (unix seconds); rows use
``tradingDate`` + ``open/high/low/close/volume``. Prices are raw.

From the sandbox DNSE answers HTTP 401 ``{"code": "INVALID_TOKEN"}`` to anonymous
callers, so this adapter is implemented but **excluded** from the active OHLCV
chain until it is confirmed on the deployed / GitHub runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, ClassVar

from data.v2.providers.base import V2ProviderBase, unwrap_rows
from data.v2.providers.parsing import finalize_bars, make_bar
from data.v2.registry import ProviderParams, ohlcv_providers
from data.v2.schemas import AdjustedOHLCV

_SECONDS_IN_DAY = 86_400


class DnseAdapter(V2ProviderBase):
    """Reads raw daily prices from DNSE's public financial-products service."""

    id = "dnse"
    display_name = "DNSE (unofficial)"
    returns_adjusted = False

    BASE_URL = "https://services.entrade.com.vn"
    HISTORY_PATH = "/dnse-financial-products/v1/price-history"
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "VN100": "VN100",
        "HNXINDEX": "HNXINDEX",
        "UPCOMINDEX": "UPCOMINDEX",
    }

    def _history(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        rows: list[Mapping[str, Any]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._get_json(
                self.BASE_URL + self.HISTORY_PATH,
                params={
                    "symbol": symbol,
                    "resolution": "D",
                    "from": self._unix(window_start),
                    "to": self._unix(window_end) + _SECONDS_IN_DAY - 1,
                },
            )
            rows.extend(row for row in unwrap_rows(payload) if isinstance(row, Mapping))
        return finalize_bars(
            [make_bar(row, provider=self.id) for row in rows],
            start=start,
            end=end,
            provider=self.id,
        )

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return raw daily bars for ``symbol`` from DNSE."""
        return self._history(symbol.upper(), start, end)

    def get_index_ohlcv(self, index_code: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return daily bars for an index from DNSE."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, start, end)


__all__ = ["DnseAdapter"]


ohlcv_providers.register(
    id="dnse",
    name="DNSE OHLCV (unofficial, unverified)",
    description="DNSE raw daily OHLCV (anonymous access currently returns INVALID_TOKEN).",
    parameter_schema=ProviderParams,
)(DnseAdapter)
