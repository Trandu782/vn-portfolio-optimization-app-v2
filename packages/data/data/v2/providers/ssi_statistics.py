"""SSI iBoard ``statistics`` V2 adapter (keyless, undocumented).

The statistics service answers anonymously and fills six V2 data types from two
hosts, all reached with a browser User-Agent plus the iBoard ``Referer``/``Origin``:

- ``iboard-api.ssi.com.vn/statistics``:
  - ``/company/sectors-data`` — bulk ICB **level-2** map (19 groups, ~1,975
    tickers); level 1 is not exposed and stays ``None``.
  - ``/company/ssmi/stock-info`` — adjusted daily OHLCV (``close`` adjusted vs
    ``closeRaw`` raw) with matched flow (``totalMatchVol``/``totalMatchVal``) and
    total ``volume``. This adapter never reads ``closePriceAdjusted`` (it mirrors
    ``close`` in the recorded fixture, so it carries no extra information).
  - ``/company/ssmi/finance-indicator`` — quarterly ratios plus
    ``sharesOutstanding``/``marketCap``; percentages arrive as fractions and are
    normalised to 0-100 here.
  - ``/company/ssmi/corporate-actions`` — DIV/ISS events with ``exrightDate`` and
    ``ratio``.
- ``iboard-query.ssi.com.vn/stock/stock-info`` — the bulk ticker -> exchange
  security master (stocks only, ``type == "s"``).

Pagination: ``stock-info`` pages at 40 rows and ``finance-indicator`` at 20 periods;
``corporate-actions`` returns up to 100 rows per page (verified) and its
``fromDate``/``toDate`` window is capped at 366 days, so a multi-year backfill is
split into 366-day windows. ``stock-info`` also honours ``fromDate``/``toDate``
(``DD/MM/YYYY``). :mod:`data.v2.pagination` drives both the date windows and the
page crawl.

Indices are served by VCI/KBS (``V2_SPEC.md`` section 7), so ``get_index_ohlcv``
raises ``EmptyResultError`` and the OHLCV chain fails over for index requests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, ClassVar

from data.errors import EmptyResultError, ProviderError, SchemaError
from data.v2.pagination import date_windows, paginate
from data.v2.providers.base import (
    CLOSE_KEYS,
    DATE_KEYS,
    HIGH_KEYS,
    LOW_KEYS,
    OPEN_KEYS,
    VOLUME_KEYS,
    V2ProviderBase,
    coerce_date,
    coerce_float,
    coerce_int,
    pick,
    unwrap_rows,
)
from data.v2.providers.parsing import finalize_bars, numeric
from data.v2.registry import (
    ProviderParams,
    company_profile_providers,
    corporate_actions_providers,
    ohlcv_providers,
    ratios_providers,
    sector_map_providers,
    symbol_master_providers,
)
from data.v2.schemas import (
    AdjustedOHLCV,
    CompanyProfile,
    CorporateAction,
    FinancialRatios,
    SectorMap,
    SymbolMaster,
)

#: ``finance-indicator`` fields published as fractions; multiplied by 100 here so
#: every percentage in :class:`FinancialRatios` is a 0-100 number.
PERCENT_KEYS: frozenset[str] = frozenset(
    {"roe", "roa", "roic", "grossProfitMargin", "netProfitMargin", "dividendYield", "npl"}
)

#: Fields that describe the reporting period (or a flag), not a ratio value.
PERIOD_KEYS: frozenset[str] = frozenset({"yearReport", "lengthReport", "ttmType"})

#: Corporate-action event codes retained (dividend, share issue).
_ACTION_TYPES: frozenset[str] = frozenset({"DIV", "ISS"})


def _opt_float(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` for null/blank/unparseable input."""
    if value is None or value == "":
        return None
    try:
        return coerce_float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    """Return ``value`` as an int, or ``None`` for null/blank/unparseable input."""
    number = _opt_float(value)
    return None if number is None else round(number)


def _opt_str(value: Any) -> str | None:
    """Return ``value`` as a stripped string, or ``None`` when blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_date(value: Any) -> date | None:
    """Parse a provider date (ISO or ``DD/MM/YYYY``), returning ``None`` on failure."""
    if value is None or value == "":
        return None
    try:
        return coerce_date(value)
    except ValueError:
        return None


def _period(
    year_report: Any, length_report: Any, ttm_type: Any = None
) -> tuple[date | None, str]:
    """Map SSI ``yearReport``/``lengthReport``/``ttmType`` to ``(period_end, period_type)``.

    ``lengthReport`` counts the reporting quarter within the fiscal year: 1-3 are the
    Q1-Q3 filings, 4 is the Q4 filing and 5 is the audited full-year filing. The
    recorded ``finance-indicator`` fixture shows the *ratios* for the interim
    quarters (``lengthReport`` 1-3) are **trailing-twelve-month (TTM)** values, not
    single-quarter values: SSI marks those rows ``ttmType == "1"`` and the audited
    full-year row ``ttmType == "0"``. The raw income-statement fields (``revenue``,
    ``profit``) remain single-quarter, but this parser stores the ratio set, so the
    period type follows the ratios.

    ``ttmType == "0"`` (or ``lengthReport == 5``) maps to ``"annual"``;
    ``ttmType == "1"`` maps to ``"ttm"``; a null ``ttmType`` (Q4 publishes no
    ratios) falls back to ``"quarter"``. A ``yearReport`` of ``0`` is not a valid
    year, so the row is skipped (``(None, "quarter")``) instead of raising
    ``ValueError`` from ``date(0, ...)``.
    """
    year = _opt_int(year_report)
    if year is None or not 1 <= year <= 9999:
        return None, "quarter"
    length = _opt_int(length_report)
    ttm = _opt_str(ttm_type) if ttm_type is not None else None
    if length == 5 or ttm == "0":
        return date(year, 12, 31), "annual"
    month, day = {1: (3, 31), 2: (6, 30), 3: (9, 30)}.get(length or 0, (12, 31))
    period_type = "ttm" if ttm == "1" else "quarter"
    return date(year, month, day), period_type


def _make_stock_info_bar(row: Mapping[str, Any], *, provider: str) -> AdjustedOHLCV:
    """Build an adjusted bar from one ``stock-info`` row (adjusted close + raw)."""
    try:
        day = coerce_date(pick(row, DATE_KEYS))
        close = coerce_float(pick(row, CLOSE_KEYS))
        open_price = numeric(row, OPEN_KEYS, close)
        high = numeric(row, HIGH_KEYS, close)
        low = numeric(row, LOW_KEYS, close)
        volume = coerce_int(numeric(row, VOLUME_KEYS, 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaError(
            f"{provider} stock-info row does not match the documented schema: {exc}",
            provider=provider,
            cause=exc,
        ) from exc
    return AdjustedOHLCV(
        date=day,
        open=open_price,
        high=high,
        low=low,
        close=close,
        close_raw=_opt_float(row.get("closeRaw")),
        volume=volume,
        matched_volume=_opt_int(row.get("totalMatchVol")),
        matched_value=_opt_float(row.get("totalMatchVal")),
        value=None,
        source=provider,
    )


def _parse_corporate_action(
    row: Mapping[str, Any], *, ticker: str, provider: str
) -> CorporateAction | None:
    """Build a :class:`CorporateAction` from one row, or ``None`` for other events."""
    event_type = str(row.get("eventListCode") or "").strip().upper()
    if event_type not in _ACTION_TYPES:
        return None
    return CorporateAction(
        ticker=ticker,
        event_type=event_type,
        exright_date=_opt_date(row.get("exrightDate")),
        record_date=_opt_date(row.get("recordDate")),
        issue_date=_opt_date(row.get("issueDate")),
        ratio=_opt_float(row.get("ratio")),
        value=_opt_float(row.get("value")),
        exchange=_opt_str(row.get("exchange")),
        description=_opt_str(row.get("eventDescription")),
        source=provider,
    )


def parse_ssi_finance_rows(
    rows: Sequence[Any], *, ticker: str, provider: str
) -> list[FinancialRatios]:
    """Turn ``finance-indicator`` rows into normalized :class:`FinancialRatios`.

    Percentages in :data:`PERCENT_KEYS` are multiplied by 100 (SSI publishes them
    as fractions), period metadata is mapped with :func:`_period`, and every other
    numeric field is passed through. A row with no usable period or no numeric
    ratio is skipped; no parsable rows raises ``SchemaError``.
    """
    records: list[FinancialRatios] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        period, period_type = _period(
            row.get("yearReport"), row.get("lengthReport"), row.get("ttmType")
        )
        if period is None:
            continue
        ratios: dict[str, float | None] = {}
        for key, value in row.items():
            name = str(key)
            if name in PERIOD_KEYS:
                continue
            number = _opt_float(value)
            if number is None:
                ratios[name] = None
                continue
            ratios[name] = number * 100.0 if name in PERCENT_KEYS else number
        if not ratios:
            continue
        records.append(
            FinancialRatios(
                ticker=ticker,
                period=period,
                period_type=period_type,  # type: ignore[arg-type]
                provider=provider,
                ratios=ratios,
            )
        )
    if not records:
        raise SchemaError(f"{provider} returned no parsable ratio periods", provider=provider)
    return records


class SsiStatisticsAdapter(V2ProviderBase):
    """Reads SSI iBoard's keyless ``statistics`` service (see the module docstring)."""

    id = "ssi_statistics"
    display_name = "SSI iBoard statistics (unofficial)"
    returns_adjusted = True
    supports_bulk_sector_map = True
    supports_free_float = False

    API_URL = "https://iboard-api.ssi.com.vn/statistics"
    QUERY_URL = "https://iboard-query.ssi.com.vn"
    SECTORS_PATH = "/company/sectors-data"
    STOCK_INFO_PATH = "/company/ssmi/stock-info"
    FINANCE_PATH = "/company/ssmi/finance-indicator"
    CORP_ACTIONS_PATH = "/company/ssmi/corporate-actions"
    SYMBOL_MASTER_PATH = "/stock/stock-info"
    HEADERS: ClassVar[dict[str, str]] = {
        "Referer": "https://iboard.ssi.com.vn/",
        "Origin": "https://iboard.ssi.com.vn",
    }
    STOCK_INFO_PAGE_SIZE = 40
    FINANCE_PAGE_SIZE = 20
    CORP_ACTION_PAGE_SIZE = 100

    # -- payload plumbing --------------------------------------------------
    def _validate_payload(
        self, payload: Any, *, allow_null_data: bool = False
    ) -> Mapping[str, Any]:
        """Return the payload object, or raise when it is an error/invalid shape.

        ``allow_null_data`` lets an endpoint that signals "no rows" with
        ``"data": null`` (corporate actions on some tickers) read as an empty
        result instead of a schema error.
        """
        if not isinstance(payload, Mapping):
            raise SchemaError(f"{self.id} payload is not an object", provider=self.id)
        code = payload.get("code")
        if payload.get("data") is None and allow_null_data:
            if code not in (None, "SUCCESS"):
                raise EmptyResultError(
                    f"{self.id} returned {code}: {payload.get('message')}", provider=self.id
                )
            return {**payload, "data": []}
        if not isinstance(payload.get("data"), list):
            if code not in (None, "SUCCESS"):
                raise EmptyResultError(
                    f"{self.id} returned {code}: {payload.get('message')}", provider=self.id
                )
            raise SchemaError(f"{self.id} payload has no 'data' list", provider=self.id)
        return payload

    def _paged(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float],
        page_size: int,
        rows_key: str = "data",
        allow_null_data: bool = False,
        max_pages: int | None = None,
        max_rows: int | None = None,
    ) -> list[Any]:
        """Walk a statistics endpoint one page request at a time.

        ``max_pages``/``max_rows`` cap the crawl; the incremental ratio refresh
        requests only the first ``finance-indicator`` page (``max_pages=1``).
        """

        def fetch(page: int) -> Mapping[str, Any]:
            query: dict[str, str | int | float] = {**params, "page": page, "pageSize": page_size}
            return self._validate_payload(
                self._get_json(url, params=query, headers=self.HEADERS),
                allow_null_data=allow_null_data,
            )

        return paginate(fetch, rows_key=rows_key, max_pages=max_pages, max_rows=max_rows)

    # -- OHLCV (adjusted) --------------------------------------------------
    def _stock_info_rows(self, code: str, start: date, end: date) -> list[Any]:
        return self._paged(
            self.API_URL + self.STOCK_INFO_PATH,
            params={
                "symbol": code,
                "fromDate": start.strftime("%d/%m/%Y"),
                "toDate": end.strftime("%d/%m/%Y"),
            },
            page_size=self.STOCK_INFO_PAGE_SIZE,
        )

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return adjusted daily bars (with matched volume/value) for ``symbol``."""
        code = symbol.upper()
        bars: list[AdjustedOHLCV] = []
        for window_start, window_end in date_windows(start, end):
            rows = self._stock_info_rows(code, window_start, window_end)
            bars.extend(
                _make_stock_info_bar(row, provider=self.id)
                for row in rows
                if isinstance(row, Mapping)
            )
        return finalize_bars(bars, start=start, end=end, provider=self.id)

    def get_index_ohlcv(self, index_code: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Index series are served by VCI/KBS; raise so the chain fails over."""
        raise EmptyResultError(
            f"{self.id} stock-info serves stocks, not indices ({index_code})", provider=self.id
        )

    # -- sector map (bulk, ICB level 2) ------------------------------------
    def _sector_groups(self) -> list[Mapping[str, Any]]:
        payload = self._validate_payload(
            self._get_json(self.API_URL + self.SECTORS_PATH, headers=self.HEADERS)
        )
        return [row for row in payload["data"] if isinstance(row, Mapping)]

    def _symbol_master_rows(self) -> list[Mapping[str, Any]]:
        payload = self._get_json(self.QUERY_URL + self.SYMBOL_MASTER_PATH, headers=self.HEADERS)
        rows = payload if isinstance(payload, list) else unwrap_rows(payload)
        return [row for row in rows if isinstance(row, Mapping)]

    def _symbol_exchanges(self) -> dict[str, str]:
        """Return ticker -> exchange from the symbol master, or ``{}`` if unavailable."""
        try:
            pairs = (
                (
                    str(row.get("symbol") or row.get("code") or "").strip().upper(),
                    str(row.get("exchange") or "").strip().upper(),
                )
                for row in self._symbol_master_rows()
                if str(row.get("type") or "").strip().lower() == "s"
            )
            return {ticker: exchange for ticker, exchange in pairs if ticker}
        except ProviderError:
            return {}

    @staticmethod
    def _industry_name(group: Mapping[str, Any]) -> str | None:
        name = group.get("industryName")
        if isinstance(name, Mapping):
            return _opt_str(name.get("en")) or _opt_str(name.get("vi")) or _opt_str(name.get("vn"))
        return _opt_str(name)

    def _build_sector_maps(self) -> list[SectorMap]:
        exchanges = self._symbol_exchanges()
        sectors: list[SectorMap] = []
        for group in self._sector_groups():
            name = self._industry_name(group)
            code = _opt_str(group.get("industryCode"))
            companies = group.get("listCompany") or []
            for company in companies:
                if not isinstance(company, Mapping):
                    continue
                ticker = str(company.get("symbol") or "").strip().upper()
                if not ticker:
                    continue
                sectors.append(
                    SectorMap(
                        ticker=ticker,
                        exchange=exchanges.get(ticker, ""),
                        icb_level1_name=None,
                        icb_level1_code=None,
                        icb_level2_name=name,
                        icb_level2_code=code,
                        security_type=None,
                        source=self.id,
                    )
                )
        return sectors

    def get_sector_map_all(self) -> list[SectorMap]:
        """Return the bulk ICB level-2 map (level 1 stays ``None``)."""
        sectors = self._build_sector_maps()
        if not sectors:
            raise EmptyResultError("SSI returned no sector rows", provider=self.id)
        return sectors

    def get_sector_map(self, ticker: str) -> SectorMap:
        """Return one ticker's ICB level-2 mapping from the bulk map."""
        code = ticker.upper()
        for sector in self._build_sector_maps():
            if sector.ticker == code:
                return sector
        raise EmptyResultError(f"SSI lists no ICB sector for {code}", provider=self.id)

    # -- ratios / company profile ------------------------------------------
    def _finance_rows(self, code: str, *, max_pages: int | None = None) -> list[Any]:
        return self._paged(
            self.API_URL + self.FINANCE_PATH,
            params={"symbol": code},
            page_size=self.FINANCE_PAGE_SIZE,
            max_pages=max_pages,
        )

    def get_ratios(self, ticker: str) -> list[FinancialRatios]:
        """Return every normalized ratio period (TTM + annual) for ``ticker``."""
        code = ticker.upper()
        return parse_ssi_finance_rows(self._finance_rows(code), ticker=code, provider=self.id)

    def get_latest_ratios(self, ticker: str) -> list[FinancialRatios]:
        """Return the latest ratio page only (the most recent ~20 periods).

        The incremental refresh uses this so a weekly run costs about one page per
        ticker instead of the full multi-page backfill (``docs/V2_SPEC.md`` section 8).
        """
        code = ticker.upper()
        return parse_ssi_finance_rows(
            self._finance_rows(code, max_pages=1), ticker=code, provider=self.id
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Return shares outstanding and market cap from the latest period.

        Free-float is not published by SSI, so ``free_float_ratio`` stays ``None``.
        The latest period is chosen by ``(yearReport, lengthReport)`` rather than
        row order, so an upstream re-order cannot pick an older period.
        """
        code = ticker.upper()
        best: tuple[int, int] | None = None
        shares: int | None = None
        market_cap: float | None = None
        for row in self._finance_rows(code):
            if not isinstance(row, Mapping):
                continue
            row_shares = _opt_int(row.get("sharesOutstanding"))
            row_cap = _opt_float(row.get("marketCap"))
            if row_shares is None and row_cap is None:
                continue
            key = (_opt_int(row.get("yearReport")) or 0, _opt_int(row.get("lengthReport")) or 0)
            if best is None or key > best:
                best, shares, market_cap = key, row_shares, row_cap
        if best is None:
            raise EmptyResultError(
                f"SSI has no shares/market-cap row for {code}", provider=self.id
            )
        return CompanyProfile(
            ticker=code,
            free_float_ratio=None,
            shares_outstanding=shares,
            market_cap=market_cap,
            source=self.id,
        )

    # -- corporate actions -------------------------------------------------
    def get_corporate_actions(self, ticker: str, start: date, end: date) -> list[CorporateAction]:
        """Return the DIV/ISS corporate actions for ``ticker`` in ``[start, end]``.

        The endpoint caps a request at a 366-day span (a wider ``fromDate``/``toDate``
        window silently returns no rows), so the range is split into 366-day windows
        and each window is paginated. A ``data: null`` body means "no actions" for
        that window and reads as an empty list.
        """
        code = ticker.upper()
        actions: list[CorporateAction] = []
        seen: set[CorporateAction] = set()
        for window_start, window_end in date_windows(start, end, window_days=366):
            rows = self._paged(
                self.API_URL + self.CORP_ACTIONS_PATH,
                params={
                    "symbol": code,
                    "fromDate": window_start.strftime("%d/%m/%Y"),
                    "toDate": window_end.strftime("%d/%m/%Y"),
                },
                page_size=self.CORP_ACTION_PAGE_SIZE,
                allow_null_data=True,
            )
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                action = _parse_corporate_action(row, ticker=code, provider=self.id)
                if action is not None and action not in seen:
                    seen.add(action)
                    actions.append(action)
        return actions

    # -- symbol master -----------------------------------------------------
    def get_symbol_master(self) -> list[SymbolMaster]:
        """Return the bulk ticker -> exchange master (stocks only, ``type == "s"``)."""
        symbols: list[SymbolMaster] = []
        for row in self._symbol_master_rows():
            if str(row.get("type") or "").strip().lower() != "s":
                continue
            ticker = str(row.get("symbol") or row.get("code") or "").strip().upper()
            if not ticker:
                continue
            name = _opt_str(row.get("clientNameEn")) or _opt_str(row.get("clientName"))
            symbols.append(
                SymbolMaster(
                    ticker=ticker,
                    exchange=str(row.get("exchange") or "").strip().upper(),
                    name=name,
                    security_type="s",
                    source=self.id,
                )
            )
        if not symbols:
            raise EmptyResultError("SSI returned no stock symbols", provider=self.id)
        return symbols


__all__ = [
    "PERCENT_KEYS",
    "PERIOD_KEYS",
    "SsiStatisticsAdapter",
    "parse_ssi_finance_rows",
]


def _register() -> None:
    ohlcv_providers.register(
        id="ssi_statistics",
        name="SSI iBoard statistics OHLCV (unofficial)",
        description="SSI stock-info adjusted daily OHLCV with matched volume/value.",
        parameter_schema=ProviderParams,
    )(SsiStatisticsAdapter)
    sector_map_providers.register(
        id="ssi_statistics",
        name="SSI iBoard statistics sectors (unofficial)",
        description="Bulk ICB level-2 sector map (~19 groups, ~1,975 tickers).",
        parameter_schema=ProviderParams,
    )(SsiStatisticsAdapter)
    ratios_providers.register(
        id="ssi_statistics",
        name="SSI iBoard statistics ratios (unofficial)",
        description="Quarterly ratios from finance-indicator (percentages normalized to 0-100).",
        parameter_schema=ProviderParams,
    )(SsiStatisticsAdapter)
    company_profile_providers.register(
        id="ssi_statistics",
        name="SSI iBoard statistics company profile (unofficial)",
        description="Shares outstanding and market cap from finance-indicator (no free-float).",
        parameter_schema=ProviderParams,
    )(SsiStatisticsAdapter)
    corporate_actions_providers.register(
        id="ssi_statistics",
        name="SSI iBoard statistics corporate actions (unofficial)",
        description="DIV/ISS corporate actions with exrightDate and ratio.",
        parameter_schema=ProviderParams,
    )(SsiStatisticsAdapter)
    symbol_master_providers.register(
        id="ssi_statistics",
        name="SSI iBoard statistics symbol master (unofficial)",
        description="Bulk ticker -> exchange security master (stocks only).",
        parameter_schema=ProviderParams,
    )(SsiStatisticsAdapter)


_register()





