"""VCI (Viet Capital Securities) provider (unofficial / undocumented).

History is served by ``trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart`` via
**POST**. The JSON body carries ``timeFrame`` (``ONE_DAY``), ``symbols`` (a list),
``to`` (unix seconds) and ``countBack``. The response is a list of per-symbol
objects whose ``t/o/h/l/c/v`` are parallel arrays - the same TradingView-style
shape SSI iBoard uses - so this adapter zips them into rows. Prices are raw
(unadjusted), so ``returns_adjusted_prices`` is ``False``.

Endpoints and field names were read from the open-source vnstock VCI adapter
(``vnstock/explorer/vci/const.py`` and ``quote.py``). The chart host also sits
behind a browser-header / anti-bot wall on some networks; when it answers HTML the
shared client raises ``AuthRequiredError`` and the failover chain moves on. VCI
only publishes price history anonymously here, so the symbol list and index
constituents raise a clear error and another provider serves them.
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

#: UDF array keys used to zip the parallel arrays into rows (VCI uses the same letters).
_UDF_FIELDS = {"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}


@data_providers.register(
    id="vci",
    name="VCI (unofficial)",
    description=(
        "Viet Capital public trading API. Raw (unadjusted) daily OHLCV in "
        "TradingView UDF arrays, fetched over POST. Unofficial and undocumented; "
        "price history only."
    ),
    parameter_schema=ProviderParams,
)
class VciProvider(ProviderBase):
    """Reads daily prices from VCI's public OHLC chart endpoint."""

    id = "vci"
    display_name = "VCI (unofficial)"
    returns_adjusted_prices = False
    supports_indexes = True

    BASE_URL = "https://trading.vietcap.com.vn/api"
    HISTORY_PATH = "/chart/OHLCChart/gap-chart"
    HEADERS: ClassVar[dict[str, str]] = {
        "Referer": "https://trading.vietcap.com.vn/",
        "Origin": "https://trading.vietcap.com.vn",
    }
    #: Canonical index code -> VCI ticker spelling.
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "HNXINDEX": "HNXIndex",
        "UPCOMINDEX": "HNXUpcomIndex",
    }

    def _udf_rows(self, payload: Any) -> list[Mapping[str, Any]]:
        """Turn the per-symbol array document into row dicts."""
        if isinstance(payload, Mapping) and "data" in payload:
            payload = payload["data"]
        if isinstance(payload, Mapping) and "t" in payload:
            payload = [payload]  # a single symbol object rather than a list
        if not isinstance(payload, list) or not payload:
            return []
        symbol_data = payload[0]
        if not isinstance(symbol_data, Mapping) or not isinstance(symbol_data.get("t"), list):
            raise SchemaError("VCI payload missing the 't' array", provider=self.id)
        times = symbol_data["t"]
        columns = {name: symbol_data.get(letter, []) for letter, name in _UDF_FIELDS.items()}
        for name, values in columns.items():
            if not isinstance(values, list) or len(values) != len(times):
                raise SchemaError(
                    f"VCI column {name!r} is not aligned with 't'", provider=self.id
                )
        return [
            {name: columns[name][index] for name in columns} for index in range(len(times))
        ]

    def _history(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        rows: list[Mapping[str, Any]] = []
        for window_start, window_end in self._chunks(start, end):
            # countBack is bars counted back from ``to``; over-request to cover
            # weekends/holidays, then trim to the requested window below.
            count_back = (window_end - window_start).days + 15
            payload = self._post_json(
                self.BASE_URL + self.HISTORY_PATH,
                json_body={
                    "timeFrame": "ONE_DAY",
                    "symbols": [symbol],
                    "to": self._unix(window_end) + 86_399,
                    "countBack": count_back,
                },
                headers=self.HEADERS,
            )
            rows.extend(self._udf_rows(payload))
        bars = self._parse_rows(rows)
        in_range = [bar for bar in bars if start <= bar.date <= end]
        return canonicalize_price_bars(in_range, provider=self.id)

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Return raw daily bars for ``symbol`` from VCI."""
        return self._history(symbol.upper(), start, end)

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for an index, translating to VCI's code spelling."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, start, end)

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Not exposed anonymously by VCI; the chain uses another provider."""
        raise EmptyResultError(
            "VCI does not expose index constituents anonymously", provider=self.id
        )

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        """Not exposed anonymously by VCI; the chain uses another provider."""
        raise EmptyResultError(
            "VCI does not expose a symbol list anonymously", provider=self.id
        )
