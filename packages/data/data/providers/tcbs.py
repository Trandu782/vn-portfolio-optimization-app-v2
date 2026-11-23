"""TCBS provider (unofficial / undocumented).

Endpoint and field names were read from the open-source vnstock TCBS adapter
(``vnstock/explorer/tcbs/const.py``): history lives at
``/stock-insight/v2/stock/bars-long-term`` and each row uses ``tradingDate`` plus
``open/high/low/close/volume``. TCBS returns **raw** prices, so
``returns_adjusted_prices`` is ``False`` and ``adj_close`` mirrors ``close``.

TCBS is anonymous but sits behind a browser-header check, so requests send a
``Referer``/``Origin`` and the shared client's normal User-Agent. If the site
starts returning an auth wall or HTML the base class raises ``AuthRequiredError``
and the failover chain moves on.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, ClassVar

from data.errors import EmptyResultError, HttpStatusError, SchemaError
from data.models import PriceBar, SymbolInfo
from data.providers.base import ProviderBase, pick
from data.registry import ProviderParams, data_providers
from data.validation import canonicalize_price_bars


@data_providers.register(
    id="tcbs",
    name="TCBS (unofficial)",
    description=(
        "Anonymous TCBS public API. Raw (unadjusted) daily OHLCV; "
        "browser Referer required. Unofficial and undocumented."
    ),
    parameter_schema=ProviderParams,
)
class TcbsProvider(ProviderBase):
    """Reads daily prices from TCBS's public stock-insight endpoints."""

    id = "tcbs"
    display_name = "TCBS (unofficial)"
    returns_adjusted_prices = False
    supports_indexes = True

    BASE_URL = "https://apipubaws.tcbs.com.vn"
    HISTORY_PATH = "/stock-insight/v2/stock/bars-long-term"
    HISTORY_FALLBACK_PATH = "/stock-insight/v2/stock/bars"
    LIST_PATH = "/stock-insight/v2/stock/all"
    CONSTITUENTS_PATH = "/stock-insight/v2/index/constituents"
    HEADERS: ClassVar[dict[str, str]] = {
        "Referer": "https://tcinvest.tcbs.com.vn/",
        "Origin": "https://tcinvest.tcbs.com.vn",
    }
    #: Canonical index code -> TCBS ticker spelling.
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "HNXINDEX": "HNXIndex",
        "UPCOMINDEX": "UPCOM",
    }

    def _fetch_history(self, ticker: str, kind: str, start: date, end: date) -> Any:
        params: dict[str, str | int] = {
            "ticker": ticker,
            "type": kind,
            "resolution": "D",
            "from": self._unix(start),
            "to": self._unix(end) + 86_399,
        }
        try:
            return self._get_json(
                self.BASE_URL + self.HISTORY_PATH, params=params, headers=self.HEADERS
            )
        except HttpStatusError as exc:
            if exc.status_code == 404:
                return self._get_json(
                    self.BASE_URL + self.HISTORY_FALLBACK_PATH,
                    params=params,
                    headers=self.HEADERS,
                )
            raise

    def _history(self, ticker: str, kind: str, start: date, end: date) -> list[PriceBar]:
        rows: list[Mapping[str, Any]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._fetch_history(ticker, kind, window_start, window_end)
            rows.extend(row for row in self._rows(payload) if isinstance(row, Mapping))
        bars = self._parse_rows(rows, date_keys=("tradingDate",))
        return canonicalize_price_bars(bars, provider=self.id)

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Return raw daily bars for ``symbol`` from TCBS."""
        return self._history(symbol.upper(), "stock", start, end)

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for an index, translating to TCBS's code spelling."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, "index", start, end)

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Return the symbols that make up ``index_code``."""
        payload = self._get_json(
            self.BASE_URL + self.CONSTITUENTS_PATH,
            params={"index": index_code.upper()},
            headers=self.HEADERS,
        )
        codes: list[str] = []
        for row in self._rows(payload):
            if isinstance(row, Mapping):
                try:
                    codes.append(str(pick(row, ("ticker", "symbol", "code"))).upper())
                except KeyError as exc:
                    raise SchemaError(
                        "constituent row missing ticker", provider=self.id, cause=exc
                    ) from exc
            else:
                codes.append(str(row).upper())
        if not codes:
            raise EmptyResultError("no constituents returned", provider=self.id)
        return codes

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        """Return the symbols TCBS lists, filtered by ``exchange`` when given."""
        payload = self._get_json(self.BASE_URL + self.LIST_PATH, headers=self.HEADERS)
        symbols: list[SymbolInfo] = []
        for row in self._rows(payload):
            if not isinstance(row, Mapping):
                continue
            try:
                code = str(pick(row, ("ticker", "symbol", "code"))).upper()
            except KeyError:
                continue
            board = pick(row, ("exchange", "exchangeName", "board"), required=False)
            board_name = str(board).upper() if board else exchange.upper()
            if exchange and board_name != exchange.upper():
                continue
            name = pick(row, ("companyName", "organName", "name"), required=False)
            symbols.append(
                SymbolInfo(
                    code=code,
                    exchange=board_name,
                    name=str(name) if name is not None else None,
                    type="stock",
                    source=self.id,
                )
            )
        if not symbols:
            raise EmptyResultError("no symbols returned", provider=self.id)
        return symbols
