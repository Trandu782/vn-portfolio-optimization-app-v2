"""VCI (Viet Capital Securities) V2 adapter.

Verified: daily OHLCV from ``POST /chart/OHLCChart/gap-chart`` (TradingView UDF
arrays ``t/o/h/l/c/v``). A live overlap check against KBS on VCB gave a close
ratio of 0.999, so VCI returns **raw** prices, not adjusted ones, and
``returns_adjusted`` is ``False``.

NOT verified from the sandbox (each returns the SPA HTML shell or is unreachable):
- ICB sector map (``/company/companyProfile`` candidate)
- financial ratios (``/financial/ratio`` candidate)
- index constituents (``/market/index/constituents`` candidate)

Those three are implemented defensively but excluded from the active chains until
they are confirmed on the deployed / GitHub runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, ClassVar

from data.errors import EmptyResultError, SchemaError
from data.v2.providers.base import V2ProviderBase, pick, unwrap_rows, zip_udf_rows
from data.v2.providers.parsing import finalize_bars, make_bar, parse_financial_ratios
from data.v2.registry import (
    ProviderParams,
    constituents_providers,
    ohlcv_providers,
    ratios_providers,
    sector_map_providers,
)
from data.v2.schemas import (
    AdjustedOHLCV,
    FinancialRatios,
    IndexConstituents,
    SectorMap,
)

_SECONDS_IN_DAY = 86_400


class VciAdapter(V2ProviderBase):
    """Reads raw daily prices (and unverified sector/ratios) from VCI."""

    id = "vci"
    display_name = "VCI (unofficial)"
    returns_adjusted = False
    supports_bulk_sector_map = False

    BASE_URL = "https://trading.vietcap.com.vn/api"
    HISTORY_PATH = "/chart/OHLCChart/gap-chart"
    SECTOR_PATH = "/company/companyProfile"  # UNVERIFIED
    RATIOS_PATH = "/financial/ratio"  # UNVERIFIED
    CONSTITUENTS_PATH = "/market/index/constituents"  # UNVERIFIED
    HEADERS: ClassVar[dict[str, str]] = {
        "Referer": "https://trading.vietcap.com.vn/",
        "Origin": "https://trading.vietcap.com.vn",
    }
    INDEX_MAP: ClassVar[dict[str, str]] = {
        "VNINDEX": "VNINDEX",
        "VN30": "VN30",
        "VN100": "VN100",
        "HNXINDEX": "HNXIndex",
        "UPCOMINDEX": "HNXUpcomIndex",
    }

    def _history(self, ticker: str, start: date, end: date) -> list[AdjustedOHLCV]:
        rows: list[dict[str, Any]] = []
        for window_start, window_end in self._chunks(start, end):
            payload = self._post_json(
                self.BASE_URL + self.HISTORY_PATH,
                json_body={
                    "timeFrame": "ONE_DAY",
                    "symbols": [ticker],
                    "to": self._unix(window_end) + _SECONDS_IN_DAY - 1,
                    "countBack": (window_end - window_start).days + 15,
                },
                headers=self.HEADERS,
            )
            rows.extend(zip_udf_rows(payload, provider=self.id))
        return finalize_bars(
            [make_bar(row, provider=self.id) for row in rows],
            start=start,
            end=end,
            provider=self.id,
        )

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return raw daily bars for ``symbol`` from VCI."""
        return self._history(symbol.upper(), start, end)

    def get_index_ohlcv(self, index_code: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return daily bars for an index from VCI."""
        ticker = self.INDEX_MAP.get(index_code.upper(), index_code.upper())
        return self._history(ticker, start, end)

    # -- sector map (UNVERIFIED) -------------------------------------------
    def get_sector_map(self, ticker: str) -> SectorMap:
        """Return one ticker's ICB mapping (candidate endpoint; unverified)."""
        code = ticker.upper()
        payload = self._get_json(
            self.BASE_URL + self.SECTOR_PATH, params={"symbol": code}, headers=self.HEADERS
        )
        return _sector_from(payload, ticker=code, provider=self.id)

    def get_sector_map_all(self) -> list[SectorMap]:
        """VCI has no anonymous bulk ICB endpoint; the runner falls back per ticker."""
        raise NotImplementedError("VCI exposes the ICB map per ticker only")

    # -- ratios (UNVERIFIED) ------------------------------------------------
    def get_ratios(self, ticker: str) -> list[FinancialRatios]:
        """Return ratios from VCI (candidate endpoint; unverified)."""
        code = ticker.upper()
        payload = self._get_json(
            self.BASE_URL + self.RATIOS_PATH, params={"symbol": code}, headers=self.HEADERS
        )
        return parse_financial_ratios(payload, ticker=code, provider=self.id)

    # -- constituents (UNVERIFIED) ------------------------------------------
    def get_index_constituents(self, index_code: str) -> IndexConstituents:
        """Return index members from VCI (candidate endpoint; unverified)."""
        code = index_code.upper()
        payload = self._get_json(
            self.BASE_URL + self.CONSTITUENTS_PATH,
            params={"index": code},
            headers=self.HEADERS,
        )
        members: list[str] = []
        for row in unwrap_rows(payload):
            if isinstance(row, Mapping):
                symbol = pick(row, ("ticker", "symbol", "code"), required=False)
                if symbol:
                    members.append(str(symbol).upper())
            elif isinstance(row, str) and row:
                members.append(row.upper())
        if not members:
            raise EmptyResultError("VCI returned no constituents", provider=self.id)
        return IndexConstituents(index=code, members=members, as_of=None, source=self.id)


def _opt_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _sector_from(payload: Any, *, ticker: str, provider: str) -> SectorMap:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, Mapping):
        raise SchemaError("VCI company profile is not an object", provider=provider)
    inner: Any = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(inner, Mapping):
        raise SchemaError("VCI company profile is not an object", provider=provider)
    return SectorMap(
        ticker=ticker,
        exchange=str(pick(inner, ("exchange", "market"), required=False) or "").upper(),
        icb_level1_name=_opt_str(pick(inner, ("icbName", "icbLv1Name"), required=False)),
        icb_level1_code=_opt_str(pick(inner, ("icbCode", "icbLv1Code"), required=False)),
        icb_level2_name=_opt_str(pick(inner, ("icbLv2Name",), required=False)),
        icb_level2_code=_opt_str(pick(inner, ("icbLv2Code",), required=False)),
        security_type=_opt_str(pick(inner, ("securityType", "type"), required=False)),
        source=provider,
    )


__all__ = ["VciAdapter"]


def _register() -> None:
    ohlcv_providers.register(
        id="vci",
        name="VCI OHLCV (unofficial)",
        description="Viet Capital raw daily OHLCV for stocks and indices (POST UDF chart).",
        parameter_schema=ProviderParams,
    )(VciAdapter)
    sector_map_providers.register(
        id="vci",
        name="VCI sector map (unofficial, unverified)",
        description="Viet Capital ICB classification per ticker (candidate endpoint; unverified).",
        parameter_schema=ProviderParams,
    )(VciAdapter)
    ratios_providers.register(
        id="vci",
        name="VCI ratios (unofficial, unverified)",
        description="Viet Capital financial ratios (candidate endpoint; unverified).",
        parameter_schema=ProviderParams,
    )(VciAdapter)
    constituents_providers.register(
        id="vci",
        name="VCI constituents (unofficial, unverified)",
        description="Viet Capital index membership (candidate endpoint; unverified).",
        parameter_schema=ProviderParams,
    )(VciAdapter)


_register()
