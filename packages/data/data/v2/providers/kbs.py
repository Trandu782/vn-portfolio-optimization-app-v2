"""KBS (KB Securities) V2 adapter.

Verified endpoints (recorded from a live response on 2026-11-22):
- OHLCV: ``GET /stocks/{symbol}/data_day?sdate=DD-MM-YYYY&edate=DD-MM-YYYY``
  returns ``{"symbol": ..., "data_day": [{"t", "o", "h", "l", "c", "v"}]}``.
- Index OHLCV: ``GET /index/{symbol}/data_day`` (same shape).
- Constituents: ``GET /index/{group}/stocks`` returns ``{"status": 200, "data": [...]}``
  for groups HOSE, HNX, UPCOM, ``30`` (VN30) and ``100`` (VN100).

Prices are raw VND (VCB printed around 60,120 in Dec 2024), so
``returns_adjusted`` is ``False``. The anonymous finance endpoint was **not
verified** from the sandbox, so ``get_ratios`` targets a candidate path and the
adapter is excluded from the active ratios chain.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import ClassVar

from data.errors import EmptyResultError, SchemaError
from data.v2.providers.base import V2ProviderBase, unwrap_rows
from data.v2.providers.parsing import finalize_bars, make_bar, parse_financial_ratios
from data.v2.registry import (
    ProviderParams,
    constituents_providers,
    ohlcv_providers,
    ratios_providers,
    symbol_master_providers,
)
from data.v2.schemas import AdjustedOHLCV, FinancialRatios, IndexConstituents, SymbolMaster


class KbsAdapter(V2ProviderBase):
    """Reads raw daily prices, index groups and (unverified) ratios from KBS."""

    id = "kbs"
    display_name = "KBS (unofficial)"
    returns_adjusted = False

    BASE_URL = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
    HISTORY_PATH = "/{kind}/{symbol}/data_day"
    GROUP_MEMBERS_PATH = "/index/{group}/stocks"
    SYMBOL_MASTER_PATH = "/stock/search/data"
    RATIOS_PATH = "/stocks/{symbol}/financial-ratio"  # UNVERIFIED

    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "VN100": "VN100",
        "HNXINDEX": "HNXINDEX",
        "UPCOMINDEX": "UPCOMINDEX",
    }
    INDEX_GROUP_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "HOSE",
        "HOSE": "HOSE",
        "VN30": "30",
        "VN100": "100",
        "HNX": "HNX",
        "HNXINDEX": "HNX",
        "HNX30": "HNX30",
        "UPCOM": "UPCOM",
        "UPCOMINDEX": "UPCOM",
    }

    def _history(self, kind: str, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        payload = self._get_json(
            self.BASE_URL + self.HISTORY_PATH.format(kind=kind, symbol=symbol),
            params={"sdate": start.strftime("%d-%m-%Y"), "edate": end.strftime("%d-%m-%Y")},
        )
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data_day"), list):
            raise SchemaError("KBS payload missing the 'data_day' array", provider=self.id)
        rows = [row for row in payload["data_day"] if isinstance(row, Mapping)]
        return finalize_bars(
            [make_bar(row, provider=self.id) for row in rows],
            start=start,
            end=end,
            provider=self.id,
        )

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return raw daily bars for ``symbol`` from KBS."""
        return self._history("stocks", symbol.upper(), start, end)

    def get_index_ohlcv(self, index_code: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return daily bars for an index from KBS."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history("index", ticker, start, end)

    def get_index_constituents(self, index_code: str) -> IndexConstituents:
        """Return an index's members from KBS's anonymous group endpoint."""
        code = index_code.upper()
        group = self.INDEX_GROUP_MAP.get(code)
        if group is None:
            raise EmptyResultError(f"KBS publishes no group for index {code}", provider=self.id)
        payload = self._get_json(self.BASE_URL + self.GROUP_MEMBERS_PATH.format(group=group))
        members = [str(row).upper() for row in unwrap_rows(payload) if isinstance(row, str) and row]
        if not members:
            raise EmptyResultError("KBS returned no constituents", provider=self.id)
        return IndexConstituents(index=code, members=members, as_of=None, source=self.id)

    def get_symbol_master(self) -> list[SymbolMaster]:
        """Return the bulk KBS tradable-security list (ticker, exchange, type, name)."""
        payload = self._get_json(self.BASE_URL + self.SYMBOL_MASTER_PATH)
        rows = payload if isinstance(payload, list) else unwrap_rows(payload)
        symbols: list[SymbolMaster] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            ticker = str(row.get("symbol") or row.get("code") or "").strip().upper()
            if not ticker:
                continue
            name = row.get("nameEn") or row.get("name")
            symbols.append(
                SymbolMaster(
                    ticker=ticker,
                    exchange=str(row.get("exchange") or "").strip().upper(),
                    name=str(name).strip() if name else None,
                    security_type=str(row.get("type") or "").strip().lower() or None,
                    source=self.id,
                )
            )
        if not symbols:
            raise EmptyResultError("KBS returned no symbols", provider=self.id)
        return symbols

    def get_ratios(self, ticker: str) -> list[FinancialRatios]:
        """Return annual ratios from KBS (candidate, unverified endpoint)."""
        code = ticker.upper()
        payload = self._get_json(
            self.BASE_URL + self.RATIOS_PATH.format(symbol=code),
            params={"timeFrame": "data_year"},
        )
        return parse_financial_ratios(payload, ticker=code, provider=self.id, period_type="annual")


__all__ = ["KbsAdapter"]


def _register() -> None:
    constituents_providers.register(
        id="kbs",
        name="KBS constituents (unofficial)",
        description="KB Securities index/basket members (VN30, VN100, HOSE, HNX, UPCOM).",
        parameter_schema=ProviderParams,
    )(KbsAdapter)
    ohlcv_providers.register(
        id="kbs",
        name="KBS OHLCV (unofficial)",
        description="KB Securities raw daily OHLCV for stocks and indices.",
        parameter_schema=ProviderParams,
    )(KbsAdapter)
    ratios_providers.register(
        id="kbs",
        name="KBS ratios (unofficial, unverified)",
        description="KB Securities financial ratios (candidate endpoint; unverified).",
        parameter_schema=ProviderParams,
    )(KbsAdapter)
    symbol_master_providers.register(
        id="kbs",
        name="KBS symbol master (unofficial)",
        description="KB Securities bulk tradable-security list (/stock/search/data).",
        parameter_schema=ProviderParams,
    )(KbsAdapter)


_register()
