"""SSI iBoard ``statistics`` adapters against the recorded fixtures.

Covers adjusted-vs-raw OHLCV and matched volume/value, the bulk ICB level-2 sector
map, the normalized ratios, the company profile, corporate actions, the symbol
master, the symbol-master merge, the pagination helper and the adjusted-close /
corporate-action reconciliation.
"""

from __future__ import annotations

from datetime import date

import pytest
from support import load_fixture

from data.errors import EmptyResultError
from data.models import SymbolInfo
from data.offline import StaticHttpClient
from data.v2.config import V2DataSettings
from data.v2.context import build_chains
from data.v2.pagination import date_windows, has_more, paginate
from data.v2.providers.ssi_statistics import parse_ssi_finance_rows
from data.v2.ratios import GENERAL_RATIOS
from data.v2.reconcile import reconcile_corporate_actions
from data.v2.registry import (
    build_company_profile,
    build_corporate_actions,
    build_ohlcv,
    build_ratios,
    build_sector_map,
    build_symbol_master,
)
from data.v2.runner import FailoverRunner
from data.v2.schemas import AdjustedOHLCV, CorporateAction, SymbolMaster
from data.v2.symbols import MERGED_SOURCE, merge_symbol_master

START = date(2025, 12, 1)
END = date(2025, 12, 31)


def _settings() -> V2DataSettings:
    return V2DataSettings()


def _client(**extra: object) -> StaticHttpClient:
    """Fixture client. The recorded files are first-page slices, so paging is set
    to a single page to avoid the static client replaying one page many times."""
    stock_info = load_fixture("v2/ssi_iboard_stock_info.json")
    stock_info["paging"] = {"total": len(stock_info["data"]), "page": 1, "pageSize": 40}
    finance = load_fixture("v2/ssi_iboard_finance_indicator.json")
    finance["paging"] = {"total": len(finance["data"]), "page": 1, "pageSize": 20}
    routes: dict[str, object] = {
        "/ssmi/stock-info": stock_info,
        "/company/sectors-data": load_fixture("v2/ssi_iboard_sectors_data.json"),
        "/ssmi/finance-indicator": finance,
        "/ssmi/corporate-actions": load_fixture("v2/ssi_iboard_corporate_actions.json"),
        "/stock/stock-info": load_fixture("v2/ssi_iboard_stock_info_all.json"),
    }
    routes.update(extra)
    return StaticHttpClient(routes)


def test_stock_info_uses_adjusted_close_and_keeps_raw() -> None:
    adapter = build_ohlcv("ssi_statistics", _client(), _settings())
    assert adapter.returns_adjusted is True
    bars = adapter.get_ohlcv("VCB", START, END)
    assert len(bars) == 10
    latest = bars[-1]  # finalize_bars sorts ascending
    assert latest.date == date(2025, 12, 31)
    assert latest.close == 57022.75  # the adjusted "close"
    assert latest.close_raw == 57500.0  # the raw "closeRaw"
    assert latest.close != latest.close_raw
    assert latest.source == "ssi_statistics"


def test_stock_info_maps_matched_volume_value_and_keeps_total() -> None:
    latest = build_ohlcv("ssi_statistics", _client(), _settings()).get_ohlcv("VCB", START, END)[-1]
    assert latest.volume == 2_530_800  # total "volume"
    assert latest.matched_volume == 2_530_800  # "totalMatchVol"
    assert latest.matched_value == 145_491_780_000.0  # "totalMatchVal"
    assert latest.value is None  # no single total-value field on stock-info


def test_stock_info_ignores_close_price_adjusted_and_reads_close() -> None:
    row = {
        "symbol": "XYZ",
        "tradingDate": "02/01/2025",
        "open": "9.5",
        "high": "10.5",
        "low": "9.0",
        "close": "10.0",
        "closePriceAdjusted": "99.9",
        "closeRaw": "10.2",
        "volume": "3000",
        "totalMatchVol": "2500",
        "totalMatchVal": "25000000",
    }
    payload = {"code": "SUCCESS", "data": [row], "paging": {"total": 1, "page": 1, "pageSize": 40}}
    client = StaticHttpClient({"/ssmi/stock-info": payload})
    adapter = build_ohlcv("ssi_statistics", client, _settings())
    (bar,) = adapter.get_ohlcv("XYZ", date(2025, 1, 1), date(2025, 1, 5))
    assert bar.close == 10.0  # "close", never "closePriceAdjusted" (99.9)
    assert bar.close_raw == 10.2
    assert bar.volume == 3000
    assert bar.matched_volume == 2500
    assert bar.matched_value == 25_000_000.0


def test_index_ohlcv_is_not_served_by_statistics() -> None:
    adapter = build_ohlcv("ssi_statistics", _client(), _settings())
    with pytest.raises(EmptyResultError):
        adapter.get_index_ohlcv("VN30", START, END)


def test_sector_map_bulk_is_level2_only_and_fills_exchange() -> None:
    adapter = build_sector_map("ssi_statistics", _client(), _settings())
    assert adapter.supports_bulk_sector_map is True
    sectors = adapter.get_sector_map_all()
    assert len(sectors) == 1_975  # 19 ICB level-2 groups
    by_ticker = {sector.ticker: sector for sector in sectors}
    pvs = by_ticker["PVS"]
    assert pvs.icb_level2_name == "Oil & Gas"
    assert pvs.icb_level2_code == "0500"
    assert pvs.icb_level1_name is None  # level 1 is not exposed
    assert pvs.icb_level1_code is None
    assert pvs.source == "ssi_statistics"
    assert pvs.exchange == ""  # PVS is not in the recorded symbol-master slice
    assert by_ticker["SSI"].exchange == "HOSE"  # exchange comes from the master


def test_sector_map_single_ticker() -> None:
    adapter = build_sector_map("ssi_statistics", _client(), _settings())
    sector = adapter.get_sector_map("vcb")
    assert sector.ticker == "VCB"
    assert sector.icb_level2_name == "Banks"
    assert sector.icb_level2_code == "8300"
    assert sector.icb_level1_name is None
    with pytest.raises(EmptyResultError):
        adapter.get_sector_map("NOPE")


def test_ratios_normalize_percentages_and_map_periods() -> None:
    rows = load_fixture("v2/ssi_iboard_finance_indicator.json")["data"]
    records = parse_ssi_finance_rows(rows, ticker="VCB", provider="ssi_statistics")
    assert len(records) == 20
    latest = records[0]  # 2026 Q3 (newest first)
    assert latest.period == date(2026, 9, 30)
    assert latest.period_type == "ttm"
    assert latest.ratios["roe"] == pytest.approx(17.34310044)  # 0.1734... * 100
    assert latest.ratios["netProfitMargin"] == pytest.approx(45.16017794)
    assert latest.ratios["npl"] == pytest.approx(0.7057779)
    assert latest.ratios["pe"] == pytest.approx(10.0682397634)  # not a percentage
    assert latest.ratios["eps"] == pytest.approx(4985.9758189976)  # passed through
    assert "yearReport" not in latest.ratios
    assert "lengthReport" not in latest.ratios
    annual = [r for r in records if r.period == date(2025, 12, 31) and r.period_type == "annual"]
    assert annual, "the audited 2025 full-year filing (lengthReport 5) maps to annual"


def test_ratios_adapter_returns_records() -> None:
    records = build_ratios("ssi_statistics", _client(), _settings()).get_ratios("VCB")
    assert len(records) == 20
    assert records[0].provider == "ssi_statistics"
    assert records[0].ticker == "VCB"


def test_company_profile_uses_latest_shares_and_market_cap() -> None:
    adapter = build_company_profile("ssi_statistics", _client(), _settings())
    assert adapter.supports_free_float is False
    profile = adapter.get_company_profile("VCB")
    assert profile.free_float_ratio is None  # SSI publishes no free-float
    assert profile.shares_outstanding == 8_355_675_094
    assert profile.market_cap == pytest.approx(419_454_889_718_800.0)
    assert profile.source == "ssi_statistics"


def test_corporate_actions_keep_only_div_and_iss() -> None:
    adapter = build_corporate_actions("ssi_statistics", _client(), _settings())
    actions = adapter.get_corporate_actions("VCB", START, END)
    assert len(actions) == 1  # the four KQQY earnings rows are dropped
    div = actions[0]
    assert div.event_type == "DIV"
    assert div.exright_date == date(2026, 7, 23)
    assert div.ratio == pytest.approx(0.045)
    assert div.value == pytest.approx(450.0)
    assert div.exchange == "HOSE"
    assert div.source == "ssi_statistics"


def test_symbol_master_lists_stocks_only() -> None:
    adapter = build_symbol_master("ssi_statistics", _client(), _settings())
    symbols = adapter.get_symbol_master()
    assert len(symbols) == 36  # 50 rows minus 14 futures
    codes = {symbol.ticker for symbol in symbols}
    assert "SSI" in codes
    assert not any(symbol.ticker.startswith("41B") for symbol in symbols)  # futures dropped
    ssi = next(symbol for symbol in symbols if symbol.ticker == "SSI")
    assert ssi.exchange == "HOSE"
    assert ssi.security_type == "s"
    assert ssi.source == "ssi_statistics"


def test_merge_symbol_master_prefers_ssi_exchange_then_kbs() -> None:
    ssi = [
        SymbolMaster(
            ticker="VCB",
            exchange="HOSE",
            name="Vietcombank",
            security_type="s",
            source="ssi_statistics",
        ),
        SymbolMaster(
            ticker="XYZ", exchange="UPCOM", name=None, security_type="s", source="ssi_statistics"
        ),
    ]
    kbs = [
        SymbolInfo(code="VCB", exchange="hose", name="VCB", type="stock", source="kbs"),
        SymbolInfo(code="FPT", exchange="HOSE", name="FPT", type="stock", source="kbs"),
    ]
    merged = merge_symbol_master(ssi, kbs)
    by_ticker = {row.ticker: row for row in merged}
    assert set(by_ticker) == {"VCB", "FPT", "XYZ"}
    assert by_ticker["VCB"].exchange == "HOSE"  # SSI wins
    assert by_ticker["VCB"].name == "Vietcombank"  # SSI name wins
    assert by_ticker["FPT"].exchange == "HOSE"  # KBS fills the gap
    assert by_ticker["XYZ"].exchange == "UPCOM"  # SSI-only ticker kept
    assert {row.source for row in merged} == {MERGED_SOURCE}


def _bar(day: date, close: float, close_raw: float) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        close_raw=close_raw,
        volume=1000,
        source="ssi_statistics",
    )


def test_reconcile_cash_dividend_matches_expected_gap() -> None:
    before = _bar(date(2025, 7, 22), close=10_000.0, close_raw=10_000.0)
    after = _bar(date(2025, 7, 23), close=10_000.0, close_raw=9_550.0)  # adjusted continuous
    action = CorporateAction(
        ticker="XYZ",
        event_type="DIV",
        exright_date=date(2025, 7, 23),
        ratio=0.045,
        value=450.0,
        source="ssi_statistics",
    )
    (finding,) = reconcile_corporate_actions([before, after], [action])
    assert finding.status == "ok"
    assert finding.raw_gap == pytest.approx(-0.045)
    assert finding.adjusted_gap == pytest.approx(0.0)
    assert finding.removed_gap == pytest.approx(-0.045)
    assert finding.expected_gap == pytest.approx(-0.045)
    assert finding.difference == pytest.approx(0.0, abs=1e-9)


def test_reconcile_reports_a_difference_and_does_not_hide_it() -> None:
    before = _bar(date(2025, 7, 22), close=10_000.0, close_raw=10_000.0)
    after = _bar(date(2025, 7, 23), close=9_700.0, close_raw=9_550.0)  # adjusted still dropped 3%
    action = CorporateAction(
        ticker="XYZ", event_type="DIV", exright_date=date(2025, 7, 23), value=450.0,
        source="ssi_statistics",
    )
    (finding,) = reconcile_corporate_actions([before, after], [action])
    assert finding.status == "difference"
    assert finding.difference == pytest.approx(0.03, abs=1e-9)


def test_reconcile_vcb_fixture_reports_no_price_data_around_ex_date() -> None:
    """Honest gap: the recorded stock-info covers Dec 2025 but the DIV ex-date is
    Jul 2026, so the price window does not span it. FPT/HPG have no SSI fixtures at
    all, so their reconciliation is unverified (not invented)."""
    bars = build_ohlcv("ssi_statistics", _client(), _settings()).get_ohlcv("VCB", START, END)
    actions = build_corporate_actions(
        "ssi_statistics", _client(), _settings()
    ).get_corporate_actions("VCB", START, END)
    findings = reconcile_corporate_actions(bars, actions)
    assert findings
    assert all(finding.status == "no_price_data" for finding in findings)


def test_date_windows_split_a_range() -> None:
    windows = date_windows(date(2024, 1, 1), date(2026, 1, 1), window_days=365)
    assert windows[0][0] == date(2024, 1, 1)
    assert windows[-1][1] == date(2026, 1, 1)
    assert all((end - start).days < 365 for start, end in windows)
    assert date_windows(date(2025, 1, 1), date(2024, 1, 1)) == []


def test_has_more_prefers_total_pages_then_total() -> None:
    assert has_more({"totalPage": 3}, page=1, rows_on_page=10) is True
    assert has_more({"totalPage": 3}, page=3, rows_on_page=10) is False
    assert has_more({"total": 58, "pageSize": 20}, page=2, rows_on_page=20) is True
    assert has_more({"total": 58, "pageSize": 20}, page=3, rows_on_page=20) is False
    assert has_more({}, page=1, rows_on_page=10) is False


def test_paginate_respects_page_and_row_limits() -> None:
    def fetch(page: int) -> dict[str, object]:
        return {
            "data": [page * 10 + index for index in range(10)],
            "paging": {"total": 1_000, "pageSize": 10},
        }

    assert len(paginate(fetch, max_pages=3)) == 30
    assert len(paginate(fetch, max_rows=25)) == 25
    assert paginate(fetch, max_pages=1) == [10 + index for index in range(10)]


def test_runner_serves_every_ssi_data_type_through_the_chains() -> None:
    """The registry -> chains -> runner -> adapter wiring works end to end."""
    settings = _settings()
    client = _client()
    runner = FailoverRunner(settings=settings, chains=build_chains(settings, client))

    ohlcv = runner.ohlcv("VCB", START, END)
    assert ohlcv.provider == "ssi_statistics"
    assert len(ohlcv.value) == 10

    sector = runner.sector_map("VCB")
    assert sector.provider == "ssi_statistics"
    assert sector.value.icb_level2_name == "Banks"

    profile = runner.company_profile("VCB")
    assert profile.value.shares_outstanding == 8_355_675_094

    actions = runner.corporate_actions("VCB", START, END)
    assert actions.value[0].event_type == "DIV"

    master = runner.symbol_master()
    assert master.provider == "ssi_statistics"
    assert len(master.value) == 36


def test_finance_rows_with_year_report_zero_are_skipped() -> None:
    """A ``yearReport`` of 0 is not a valid year and must not raise ``ValueError``."""
    rows = [
        {"yearReport": 0, "lengthReport": 3, "eps": "1000"},
        {"yearReport": 2024, "lengthReport": 5, "eps": "2000"},
    ]
    records = parse_ssi_finance_rows(rows, ticker="HPG", provider="ssi_statistics")
    assert [record.period for record in records] == [date(2024, 12, 31)]


def test_corporate_actions_null_data_is_an_empty_result() -> None:
    """HPG-style ``data: null`` means "no actions", not a schema error."""
    client = StaticHttpClient({"/ssmi/corporate-actions": {"code": "SUCCESS", "data": None}})
    adapter = build_corporate_actions("ssi_statistics", client, _settings())
    assert adapter.get_corporate_actions("HPG", START, END) == []


class _RecordingClient(StaticHttpClient):
    """Records the query params of every request so the date window can be read back."""

    def __init__(self, routes: dict[str, object]) -> None:
        super().__init__(routes)
        self.seen_params: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> object:
        self.seen_params.append(dict(kwargs.get("params") or {}))  # type: ignore[arg-type]
        return super().get(url, **kwargs)  # type: ignore[arg-type]


def test_corporate_actions_sends_the_date_window() -> None:
    client = _RecordingClient(
        {"/ssmi/corporate-actions": {"code": "SUCCESS", "data": [], "paging": {"totalPage": 1}}}
    )
    adapter = build_corporate_actions("ssi_statistics", client, _settings())
    adapter.get_corporate_actions("VCB", date(2023, 1, 1), date(2023, 12, 31))
    assert client.seen_params
    params = client.seen_params[0]
    assert params["symbol"] == "VCB"
    assert params["fromDate"] == "01/01/2023"
    assert params["toDate"] == "31/12/2023"


def test_corporate_actions_splits_a_long_range_into_366_day_windows() -> None:
    client = _RecordingClient(
        {"/ssmi/corporate-actions": {"code": "SUCCESS", "data": [], "paging": {"totalPage": 1}}}
    )
    adapter = build_corporate_actions("ssi_statistics", client, _settings())
    adapter.get_corporate_actions("VCB", date(2023, 1, 1), date(2026, 11, 22))
    windows = [(params["fromDate"], params["toDate"]) for params in client.seen_params]
    assert len(windows) >= 4
    assert windows[0] == ("01/01/2023", "01/01/2024")


def test_reconcile_combines_actions_sharing_one_ex_date() -> None:
    before = _bar(date(2025, 7, 22), close=10_000.0, close_raw=10_000.0)
    after = _bar(date(2025, 7, 23), close=10_000.0, close_raw=8_816.78)
    actions = [
        CorporateAction(
            ticker="XYZ", event_type="ISS", exright_date=date(2025, 7, 23), ratio=0.07,
            source="ssi_statistics",
        ),
        CorporateAction(
            ticker="XYZ", event_type="ISS", exright_date=date(2025, 7, 23), ratio=0.06,
            source="ssi_statistics",
        ),
    ]
    (finding,) = reconcile_corporate_actions([before, after], actions)
    assert finding.event_type == "ISS/ISS"
    assert finding.action_ratio == pytest.approx(0.13)
    # The bonus-share model is not applied to an ISS (no subscription price), so the
    # removed gap is reported as unsupported rather than compared with it.
    assert finding.expected_gap is None
    assert finding.status == "unsupported"


def test_reconcile_flags_a_spurious_adjustment_gain() -> None:
    # EVF-like: the raw close barely moves but the adjusted close jumps +6.8% on the
    # ex-date, which is a spurious gain injected by the adjustment.
    before = _bar(date(2023, 9, 20), close=10832.47, close_raw=12400.0)
    after = _bar(date(2023, 9, 21), close=11573.75, close_raw=12500.0)
    action = CorporateAction(
        ticker="EVF",
        event_type="ISS",
        exright_date=date(2023, 9, 21),
        ratio=1.0,
        source="ssi_statistics",
    )
    (finding,) = reconcile_corporate_actions([before, after], [action])
    assert finding.status == "adjustment_suspect"
    assert finding.adjusted_gap == pytest.approx(11573.75 / 10832.47 - 1.0)


def test_reconcile_leaves_a_rights_issue_unsupported() -> None:
    # NVL-like: the raw close falls a little and the adjusted close is almost flat, so
    # the ISS is unverifiable (no subscription price) but not a spurious gain.
    before = _bar(date(2026, 9, 29), close=10224.81, close_raw=10300.0)
    after = _bar(date(2026, 9, 30), close=10200.0, close_raw=10200.0)
    action = CorporateAction(
        ticker="NVL",
        event_type="ISS",
        exright_date=date(2026, 9, 30),
        ratio=0.33333333,
        source="ssi_statistics",
    )
    (finding,) = reconcile_corporate_actions([before, after], [action])
    assert finding.status == "unsupported"


def test_ratios_interim_quarters_are_ttm() -> None:
    rows = load_fixture("v2/ssi_iboard_finance_indicator.json")["data"]
    records = parse_ssi_finance_rows(rows, ticker="VCB", provider="ssi_statistics")
    by_key = {(record.period, record.period_type): record for record in records}
    assert (date(2026, 9, 30), "ttm") in by_key
    assert (date(2025, 12, 31), "annual") in by_key
    # Q4 (lengthReport 4, ttmType null) publishes no ratios; it stays "quarter".
    assert (date(2025, 12, 31), "quarter") in by_key
    q4 = by_key[(date(2025, 12, 31), "quarter")]
    ratio_keys = {
        "eps", "pe", "roe", "roa", "roic", "grossProfitMargin", "netProfitMargin",
        "debtEquity", "debtAsset", "currentRatio", "quickRatio", "pb",
        "dividendYield", "npl",
    }
    assert all(q4.ratios.get(key) is None for key in ratio_keys)


def test_get_latest_ratios_requests_only_the_first_page() -> None:
    client = _RecordingClient(
        {
            "/ssmi/finance-indicator": {
                "code": "SUCCESS",
                "data": [
                    {"yearReport": 2026, "lengthReport": 3, "ttmType": "1", "eps": "1000"}
                ],
                "paging": {"total": 58, "pageSize": 20},
            }
        }
    )
    adapter = build_ratios("ssi_statistics", client, _settings())
    records = adapter.get_latest_ratios("VCB")  # type: ignore[attr-defined]
    assert len(records) == 1
    assert records[0].period_type == "ttm"
    assert [params.get("page") for params in client.seen_params] == [1]


@pytest.mark.parametrize(
    ("ticker", "fixture"),
    [
        ("FPT", "v2/ssi_iboard_finance_indicator_fpt.json"),
        ("HPG", "v2/ssi_iboard_finance_indicator_hpg.json"),
        ("VNM", "v2/ssi_iboard_finance_indicator_vnm.json"),
    ],
)
def test_non_financial_fixtures_keep_ttm_mapping_and_general_keys(
    ticker: str, fixture: str
) -> None:
    """Recorded FPT/HPG/VNM pages confirm the TTM/annual/quarter mapping and that
    every GENERAL_RATIOS key is populated (npl is sent but 0.0 for non-financials)."""
    rows = load_fixture(fixture)["data"]
    records = parse_ssi_finance_rows(rows, ticker=ticker, provider="ssi_statistics")
    by_key = {(record.period, record.period_type): record for record in records}
    assert (date(2026, 9, 30), "ttm") in by_key
    assert (date(2025, 12, 31), "annual") in by_key
    assert (date(2025, 12, 31), "quarter") in by_key
    latest = by_key[(date(2026, 9, 30), "ttm")]
    assert latest.ratios.get("npl") == pytest.approx(0.0)
    for key in GENERAL_RATIOS:
        assert latest.ratios.get(key) is not None, key

