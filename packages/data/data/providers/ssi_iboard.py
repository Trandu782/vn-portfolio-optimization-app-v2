"""SSI iBoard provider (unofficial / undocumented).

SSI's public iBoard chart gateway (``iboard-query.ssi.com.vn``) exposes daily
history through ``/dchart/api/history`` and returns a TradingView-style UDF
document (``{"s": "ok", "t": [...], "o": [...], "h": [...], "l": [...],
"c": [...], "v": [...]}``) rather than row objects, so this adapter zips the
parallel arrays into bars. Prices are **raw**, so ``returns_adjusted_prices`` is
``False``.

iBoard only publishes price history anonymously; it does not expose a symbol
list or index constituents without a session, so those two methods raise a clear
error and the failover chain uses another provider for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, ClassVar

from data.errors import EmptyResultError, SchemaError
from data.models import PriceBar, SymbolInfo
from data.providers.base import ProviderBase
from data.registry import ProviderParams, data_providers
from data.validation import canonicalize_price_bars

#: UDF keys used to zip the parallel arrays into rows.
_UDF_FIELDS = {"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}


@data_providers.register(
    id="ssi_iboard",
    name="SSI iBoard (unofficial)",
    description=(
        "SSI public iBoard chart gateway. Raw (unadjusted) daily OHLCV in "
        "TradingView UDF arrays. Unofficial and undocumented; price history only."
    ),
    parameter_schema=ProviderParams,
)
class SsiIboardProvider(ProviderBase):
    """Reads daily prices from SSI's public iBoard dchart endpoint."""

    id = "ssi_iboard"
    display_name = "SSI iBoard (unofficial)"
    returns_adjusted_prices = False
    supports_indexes = True

    BASE_URL = "https://iboard-query.ssi.com.vn"
    HISTORY_PATH = "/dchart/api/history"
    HEADERS: ClassVar[dict[str, str]] = {"Referer": "https://iboard.ssi.com.vn/"}
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "HNXINDEX": "HNXIndex",
        "UPCOMINDEX": "UPCOM",
    }

    def _udf_rows(self, payload: Any) -> list[Mapping[str, Any]]:
        """Turn a UDF document into row dicts, or accept a plain row list."""
        if isinstance(payload, Mapping) and "s" in payload:
            status = payload.get("s")
            if status == "no_data":
                return []
            if not isinstance(payload.get("t"), list):
                raise SchemaError("UDF payload missing 't' array", provider=self.id)
            times = payload["t"]
            columns = {name: payload.get(letter, []) for letter, name in _UDF_FIELDS.items()}
            for name, values in columns.items():
                if not isinstance(values, list) or len(values) != len(times):
                    raise SchemaError(
                        f"UDF column {name!r} is not aligned with 't'", provider=self.id
                    )
            return [
                {name: columns[name][index] for name in columns}
                for index in range(len(times))
            ]
        return [row for row in self._rows(payload) if isinstance(row, Mapping)]

    def _history(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        rows: list[Mapping[str, Any]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._get_json(
                self.BASE_URL + self.HISTORY_PATH,
                params={
                    "resolution": "D",
                    "symbol": symbol,
                    "from": self._unix(window_start),
                    "to": self._unix(window_end) + 86_399,
                },
                headers=self.HEADERS,
            )
            rows.extend(self._udf_rows(payload))
        bars = self._parse_rows(rows, date_keys=("time", "date", "tradingDate"))
        return canonicalize_price_bars(bars, provider=self.id)

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Return raw daily bars for ``symbol`` from SSI iBoard."""
        return self._history(symbol.upper(), start, end)

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for an index from SSI iBoard."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, start, end)

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Not exposed anonymously by iBoard; the chain uses another provider."""
        raise EmptyResultError(
            "SSI iBoard does not expose index constituents anonymously",
            provider=self.id,
        )

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        """Not exposed anonymously by iBoard; the chain uses another provider."""
        raise EmptyResultError(
            "SSI iBoard does not expose a symbol list anonymously", provider=self.id
        )
