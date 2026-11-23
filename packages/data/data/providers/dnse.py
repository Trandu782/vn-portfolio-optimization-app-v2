"""DNSE provider (unofficial / undocumented).

History is served by ``services.entrade.com.vn/dnse-financial-products/v1/
price-history`` with ``symbol``/``resolution``/``from``/``to`` (unix seconds).
Rows use ``tradingDate`` + ``open/high/low/close/volume``; DNSE returns **raw**
prices, so ``returns_adjusted_prices`` is ``False``.

DNSE has started returning ``{"code": "INVALID_TOKEN"}`` to anonymous callers on
some endpoints. The base decoder recognises that body and raises
``AuthRequiredError`` so the chain fails over instead of retrying forever.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import ClassVar

from data.errors import EmptyResultError
from data.models import PriceBar, SymbolInfo
from data.providers.base import ProviderBase, pick
from data.registry import ProviderParams, data_providers
from data.validation import canonicalize_price_bars


@data_providers.register(
    id="dnse",
    name="DNSE (unofficial)",
    description=(
        "Anonymous DNSE public API. Raw (unadjusted) daily OHLCV. "
        "Unofficial; some endpoints now answer INVALID_TOKEN to anonymous "
        "callers, in which case the failover chain skips it."
    ),
    parameter_schema=ProviderParams,
)
class DnseProvider(ProviderBase):
    """Reads daily prices from DNSE's public financial-products service."""

    id = "dnse"
    display_name = "DNSE (unofficial)"
    returns_adjusted_prices = False
    supports_indexes = True

    BASE_URL = "https://services.entrade.com.vn"
    HISTORY_PATH = "/dnse-financial-products/v1/price-history"
    LIST_PATH = "/dnse-order-service/securities"
    CONSTITUENTS_PATH = "/dnse-financial-products/v1/index-constituents"
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "HNXINDEX": "HNXINDEX",
        "UPCOMINDEX": "UPCOMINDEX",
    }

    def _history(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        rows: list[Mapping[str, object]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._get_json(
                self.BASE_URL + self.HISTORY_PATH,
                params={
                    "symbol": symbol,
                    "resolution": "D",
                    "from": self._unix(window_start),
                    "to": self._unix(window_end) + 86_399,
                },
            )
            rows.extend(row for row in self._rows(payload) if isinstance(row, Mapping))
        bars = self._parse_rows(rows, date_keys=("tradingDate", "date", "time"))
        return canonicalize_price_bars(bars, provider=self.id)

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Return raw daily bars for ``symbol`` from DNSE."""
        return self._history(symbol.upper(), start, end)

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for an index from DNSE."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, start, end)

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Return the symbols that make up ``index_code`` from DNSE."""
        payload = self._get_json(
            self.BASE_URL + self.CONSTITUENTS_PATH, params={"index": index_code.upper()}
        )
        codes: list[str] = []
        for row in self._rows(payload):
            if isinstance(row, Mapping):
                code = pick(row, ("symbol", "ticker", "code"), required=False)
                if code is not None:
                    codes.append(str(code).upper())
            else:
                codes.append(str(row).upper())
        if not codes:
            raise EmptyResultError("no constituents returned", provider=self.id)
        return codes

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        """Return the securities DNSE lists, filtered by ``exchange`` when given."""
        payload = self._get_json(self.BASE_URL + self.LIST_PATH)
        symbols: list[SymbolInfo] = []
        for row in self._rows(payload):
            if not isinstance(row, Mapping):
                continue
            code = pick(row, ("symbol", "ticker", "code"), required=False)
            if code is None:
                continue
            board = pick(row, ("board", "exchange", "marketId"), required=False)
            board_name = str(board).upper() if board else exchange.upper() or "UNKNOWN"
            if exchange and board_name != exchange.upper():
                continue
            name = pick(row, ("name", "companyName"), required=False)
            symbols.append(
                SymbolInfo(
                    code=str(code).upper(),
                    exchange=board_name,
                    name=str(name) if name is not None else None,
                    type="stock",
                    source=self.id,
                )
            )
        if not symbols:
            raise EmptyResultError("no symbols returned", provider=self.id)
        return symbols
