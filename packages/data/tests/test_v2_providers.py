"""V2 adapters parse recorded fixtures and classify HTTP failures."""

from __future__ import annotations

from datetime import date

import pytest
from support import load_fixture

from data.errors import AuthRequiredError, EmptyResultError, RateLimitError
from data.http import HttpResponse
from data.offline import StaticHttpClient
from data.v2.config import V2DataSettings
from data.v2.errors import BlockedError
from data.v2.providers.parsing import parse_financial_ratios
from data.v2.registry import build_constituents, build_ohlcv

START = date(2024, 12, 1)
END = date(2024, 12, 31)


def _settings() -> V2DataSettings:
    return V2DataSettings()


def test_kbs_ohlcv_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/data_day": load_fixture("v2/kbs_bars.json")})
    adapter = build_ohlcv("kbs", client, _settings())
    bars = adapter.get_ohlcv("VCB", START, END)
    assert len(bars) == 22
    assert bars[0].date == date(2024, 12, 2)
    assert bars[-1].date == date(2024, 12, 31)
    assert bars[-1].close == 60120.0
    assert bars[-1].source == "kbs"
    assert adapter.returns_adjusted is False


def test_kbs_index_ohlcv_uses_index_route() -> None:
    client = StaticHttpClient({"/index/VN30/data_day": load_fixture("v2/kbs_bars.json")})
    adapter = build_ohlcv("kbs", client, _settings())
    bars = adapter.get_index_ohlcv("VN30", START, END)
    assert len(bars) == 22
    assert "/index/VN30/data_day" in client.calls[-1]


def test_kbs_constituents_parse_recorded_groups() -> None:
    client = StaticHttpClient(
        {
            "/index/30/stocks": load_fixture("v2/kbs_vn30.json"),
            "/index/HOSE/stocks": load_fixture("v2/kbs_hose.json"),
        }
    )
    adapter = build_constituents("kbs", client, _settings())
    vn30 = adapter.get_index_constituents("VN30")
    assert vn30.index == "VN30"
    assert len(vn30.members) == 30
    assert {"ACB", "VCB", "FPT"} <= set(vn30.members)
    assert vn30.source == "kbs"
    hose = adapter.get_index_constituents("HOSE")
    assert len(hose.members) == 412


def test_kbs_unknown_index_group_raises() -> None:
    adapter = build_constituents("kbs", StaticHttpClient({}), _settings())
    with pytest.raises(EmptyResultError):
        adapter.get_index_constituents("FOO")


def test_vci_ohlcv_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/chart/OHLCChart/gap-chart": load_fixture("v2/vci_bars.json")})
    adapter = build_ohlcv("vci", client, _settings())
    bars = adapter.get_ohlcv("VCB", START, END)
    assert len(bars) == 20
    assert bars[-1].date == date(2024, 12, 31)
    assert bars[-1].close == 60061.77
    assert bars[-1].source == "vci"


def test_vci_index_ohlcv_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/chart/OHLCChart/gap-chart": load_fixture("v2/vci_index.json")})
    adapter = build_ohlcv("vci", client, _settings())
    bars = adapter.get_index_ohlcv("VNINDEX", START, END)
    assert len(bars) == 20
    assert bars[-1].close == 1266.78


def test_http_403_is_blocked() -> None:
    client = StaticHttpClient(
        {"/chart/OHLCChart/gap-chart": HttpResponse(403, "<html>Just a moment...</html>", "u")}
    )
    adapter = build_ohlcv("vci", client, _settings())
    with pytest.raises(BlockedError):
        adapter.get_ohlcv("VCB", START, END)


def test_http_429_is_rate_limit() -> None:
    client = StaticHttpClient({"/chart/OHLCChart/gap-chart": HttpResponse(429, "", "u")})
    adapter = build_ohlcv("vci", client, _settings())
    with pytest.raises(RateLimitError):
        adapter.get_ohlcv("VCB", START, END)


def test_http_200_html_is_auth_wall() -> None:
    client = StaticHttpClient(
        {"/chart/OHLCChart/gap-chart": HttpResponse(200, "<!doctype html><html></html>", "u")}
    )
    adapter = build_ohlcv("vci", client, _settings())
    with pytest.raises(AuthRequiredError):
        adapter.get_ohlcv("VCB", START, END)


def test_parse_financial_ratios_normalizes_percentages() -> None:
    payload = [
        {"year": 2023, "roe": 15.2, "pe": "10.1", "ticker": "VCB"},
        {"year": 2022, "roe": 14.0, "pe": None},
    ]
    records = parse_financial_ratios(
        payload, ticker="VCB", provider="kbs", period_type="annual"
    )
    assert len(records) == 2
    assert records[0].period == date(2023, 12, 31)
    assert records[0].ratios["roe"] == 15.2
    assert records[0].ratios["pe"] == 10.1
    assert "ticker" not in records[0].ratios
    assert records[1].ratios["pe"] is None
