"""SSI iBoard V2 OHLCV adapter (last-resort fallback).

Endpoint shape from the V1 adapter: ``GET /dchart/api/history`` returns a
TradingView UDF document (``{s, t, o, h, l, c, v}``); a ``no_data`` status means
an empty range. Prices are raw.

From the sandbox iBoard answers HTTP 404 ``ERR_SQ_0001`` for the documented
query, so this adapter is implemented but **excluded** from the active OHLCV
chain until it is confirmed on the deployed / GitHub runner.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from data.errors import EmptyResultError
from data.v2.providers.base import V2ProviderBase, zip_udf_rows
from data.v2.providers.parsing import finalize_bars, make_bar
from data.v2.registry import ProviderParams, ohlcv_providers
from data.v2.schemas import AdjustedOHLCV

_SECONDS_IN_DAY = 86_400


class SsiIboardAdapter(V2ProviderBase):
    """Reads raw daily prices from SSI's public iBoard chart gateway."""

    id = "ssi_iboard"
    display_name = "SSI iBoard (unofficial)"
    returns_adjusted = False

    BASE_URL = "https://iboard-query.ssi.com.vn"
    HISTORY_PATH = "/dchart/api/history"
    HEADERS: ClassVar[dict[str, str]] = {"Referer": "https://iboard.ssi.com.vn/"}
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "VN100": "VN100",
        "HNXINDEX": "HNXIndex",
        "UPCOMINDEX": "UPCOM",
    }

    def _history(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        rows: list[dict[str, object]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._get_json(
                self.BASE_URL + self.HISTORY_PATH,
                params={
                    "resolution": "D",
                    "symbol": symbol,
                    "from": self._unix(window_start),
                    "to": self._unix(window_end) + _SECONDS_IN_DAY - 1,
                },
                headers=self.HEADERS,
            )
            rows.extend(zip_udf_rows(payload, provider=self.id))
        bars = [make_bar(row, provider=self.id) for row in rows]
        if not bars:
            raise EmptyResultError("SSI iBoard returned no rows", provider=self.id)
        return finalize_bars(bars, start=start, end=end, provider=self.id)

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return raw daily bars for ``symbol`` from SSI iBoard."""
        return self._history(symbol.upper(), start, end)

    def get_index_ohlcv(self, index_code: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return daily bars for an index from SSI iBoard."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, start, end)


__all__ = ["SsiIboardAdapter"]


ohlcv_providers.register(
    id="ssi_iboard",
    name="SSI iBoard OHLCV (unofficial, unverified)",
    description="SSI iBoard raw daily OHLCV as TradingView UDF arrays.",
    parameter_schema=ProviderParams,
)(SsiIboardAdapter)
