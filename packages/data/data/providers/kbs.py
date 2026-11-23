"""KBS (KB Securities) provider (unofficial / undocumented).

Daily history is served by ``kbbuddywts.kbsec.com.vn/iis-server/investment``:
``/stocks/{symbol}/data_day`` for stocks and ``/index/{symbol}/data_day`` for
indices, with ``sdate``/``edate`` query parameters in ``DD-MM-YYYY`` form. Each
row carries ``t`` (a ``YYYY-MM-DD HH:MM`` datetime string) plus ``o/h/l/c/v``.
Prices are raw VND (for example VNM is returned around 55000), so
``returns_adjusted_prices`` is ``False``.

Endpoint and field names were verified against a live response and the
open-source vnstock KBS adapter (``vnstock/explorer/kbs/const.py`` and
``quote.py``).

Reference data is anonymous as well and needs no token or browser header:

* ``/stock/search/data`` returns every listed security as a bare JSON array with
  ``symbol``, ``name``, ``nameEn``, ``exchange`` and ``type`` fields.
* ``/index/{group}/stocks`` returns one KBS group's member codes. ``HOSE``,
  ``HNX`` and ``UPCOM`` are the board groups behind VNINDEX/HNXINDEX/
  UPCOMINDEX, while ``30``, ``100`` and ``HNX30`` are the VN30/VN100/HNX30
  baskets - the same identifiers KBS's own web board and the vnstock KBS adapter
  use.

Both reference endpoints were verified against live responses (KBS answers with
HTTP 200 even for an unknown route, so shape checks below classify bad paths).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, ClassVar

from data.errors import EmptyResultError, SchemaError
from data.models import PriceBar, SymbolInfo
from data.providers.base import ProviderBase, pick
from data.registry import ProviderParams, data_providers
from data.validation import canonicalize_price_bars


@data_providers.register(
    id="kbs",
    name="KBS (unofficial)",
    description=(
        "KB Securities public investment API. Raw (unadjusted) daily OHLCV with "
        "DD-MM-YYYY date parameters, plus anonymous symbol search and index groups "
        "(VNINDEX, VN30, HNXINDEX, UPCOMINDEX). Unofficial and undocumented."
    ),
    parameter_schema=ProviderParams,
)
class KbsProvider(ProviderBase):
    """Reads daily prices from KB Securities' public investment service."""

    id = "kbs"
    display_name = "KBS (unofficial)"
    returns_adjusted_prices = False
    supports_indexes = True

    BASE_URL = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
    SYMBOLS_PATH = "/stock/search/data"
    GROUP_MEMBERS_PATH = "/index/{group}/stocks"
    #: Canonical index code -> KBS ticker spelling for daily index history.
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "HNXINDEX": "HNXINDEX",
        "UPCOMINDEX": "UPCOMINDEX",
    }
    #: Canonical index code -> KBS group id accepted by ``/index/{group}/stocks``.
    INDEX_GROUP_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "HOSE",
        "VN30": "30",
        "VN100": "100",
        "HNXINDEX": "HNX",
        "HNX30": "HNX30",
        "UPCOMINDEX": "UPCOM",
    }

    def _data_rows(self, payload: Any) -> list[Mapping[str, Any]]:
        """Unwrap KBS's ``data_day`` array, raising ``SchemaError`` when absent."""
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data_day"), list):
            raise SchemaError("KBS payload missing the 'data_day' array", provider=self.id)
        return [row for row in payload["data_day"] if isinstance(row, Mapping)]

    def _history(self, kind: str, symbol: str, start: date, end: date) -> list[PriceBar]:
        rows: list[Mapping[str, Any]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._get_json(
                f"{self.BASE_URL}/{kind}/{symbol}/data_day",
                params={
                    "sdate": window_start.strftime("%d-%m-%Y"),
                    "edate": window_end.strftime("%d-%m-%Y"),
                },
            )
            rows.extend(self._data_rows(payload))
        bars = self._parse_rows(rows, date_keys=("t", "time", "date", "tradingDate"))
        return canonicalize_price_bars(bars, provider=self.id)

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Return raw daily bars for ``symbol`` from KBS."""
        return self._history("stocks", symbol.upper(), start, end)

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for an index from KBS."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history("index", ticker, start, end)

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Return the member codes of ``index_code`` from KBS's group endpoint.

        ``index_code`` is a canonical code (VNINDEX, VN30, HNX30, ...); KBS uses
        its own group ids (``HOSE``, ``30``, ``HNX30``, ...), see
        :data:`INDEX_GROUP_MAP`. An unmapped code or an empty group raises
        :class:`EmptyResultError` so the failover chain moves on.
        """
        code = index_code.upper()
        group = self.INDEX_GROUP_MAP.get(code)
        if group is None:
            raise EmptyResultError(
                f"KBS publishes no group for index {code}", provider=self.id
            )
        payload = self._get_json(
            self.BASE_URL + self.GROUP_MEMBERS_PATH.format(group=group)
        )
        rows: Any = payload.get("data") if isinstance(payload, Mapping) else payload
        if not isinstance(rows, list):
            raise SchemaError("KBS group payload missing the 'data' array", provider=self.id)
        codes = [str(row).upper() for row in rows if isinstance(row, str) and row]
        if not codes:
            raise EmptyResultError("no constituents returned", provider=self.id)
        return codes

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        """Return the stock symbols KBS lists, filtered by ``exchange`` when given.

        The reference endpoint also returns bonds, covered warrants, futures and
        funds; only rows whose ``type`` is ``stock`` become :class:`SymbolInfo`
        records because the optimizer's universe is stocks. ``exchange`` is
        compared case-insensitively against KBS's ``HOSE``/``HNX``/``UPCOM``.
        """
        payload = self._get_json(self.BASE_URL + self.SYMBOLS_PATH)
        if not isinstance(payload, list):
            raise SchemaError("KBS symbol payload is not a list", provider=self.id)
        wanted = exchange.upper() if exchange else ""
        symbols: list[SymbolInfo] = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            code = pick(row, ("symbol", "ticker", "code"), required=False)
            if code is None:
                continue
            kind = str(pick(row, ("type",), required=False) or "stock").lower()
            if kind != "stock":
                continue
            board = pick(row, ("exchange", "board"), required=False)
            board_name = str(board).upper() if board else (wanted or "UNKNOWN")
            if wanted and board_name != wanted:
                continue
            name = pick(row, ("name", "nameEn"), required=False)
            symbols.append(
                SymbolInfo(
                    code=str(code).upper(),
                    exchange=board_name,
                    name=str(name) if name else None,
                    type="stock",
                    source=self.id,
                )
            )
        if not symbols:
            raise EmptyResultError("no symbols returned", provider=self.id)
        return symbols
