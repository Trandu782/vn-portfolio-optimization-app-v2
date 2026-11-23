"""Providers parse their recorded fixtures into the standard columns."""

from __future__ import annotations

from datetime import date

import pytest
from support import load_fixture

from data.errors import EmptyResultError, SchemaError
from data.offline import StaticHttpClient
from data.registry import build_provider
from data.settings import DataSettings

START = date(2024, 1, 1)
END = date(2024, 1, 10)


def _settings() -> DataSettings:
    return DataSettings(database_url="sqlite://", provider_order="tcbs")


def test_tcbs_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/bars-long-term": load_fixture("tcbs_bars.json")})
    provider = build_provider("tcbs", client, _settings())
    bars = provider.get_daily_prices("VNM", START, END)
    assert len(bars) == 5
    assert bars[0].date == date(2024, 1, 2)
    assert bars[0].close == 101.0
    assert bars[0].adj_close == bars[0].close  # TCBS is raw
    assert bars[0].source == "tcbs"


def test_tcbs_bad_schema_raises() -> None:
    client = StaticHttpClient({"/bars-long-term": load_fixture("bad_schema.json")})
    provider = build_provider("tcbs", client, _settings())
    with pytest.raises(SchemaError):
        provider.get_daily_prices("VNM", START, END)


def test_dnse_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/price-history": load_fixture("dnse_bars.json")})
    provider = build_provider("dnse", client, _settings())
    bars = provider.get_daily_prices("VNM", START, END)
    assert len(bars) == 5
    assert bars[0].close == 201.0
    assert bars[0].source == "dnse"


def test_ssi_parses_udf_fixture() -> None:
    client = StaticHttpClient({"/dchart/api/history": load_fixture("ssi_bars.json")})
    provider = build_provider("ssi_iboard", client, _settings())
    bars = provider.get_daily_prices("VNM", START, END)
    assert len(bars) == 5
    assert bars[0].date == date(2024, 1, 2)
    assert bars[0].close == 50.5
    assert bars[0].source == "ssi_iboard"


def test_vci_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/chart/OHLCChart/gap-chart": load_fixture("vci_bars.json")})
    provider = build_provider("vci", client, _settings())
    bars = provider.get_daily_prices("VNM", START, END)
    assert len(bars) == 5
    assert bars[0].date == date(2024, 1, 2)
    assert bars[0].close == 301.0
    assert bars[0].source == "vci"


def test_vci_bad_schema_raises() -> None:
    client = StaticHttpClient({"/chart/OHLCChart/gap-chart": load_fixture("bad_schema.json")})
    provider = build_provider("vci", client, _settings())
    with pytest.raises(SchemaError):
        provider.get_daily_prices("VNM", START, END)


def test_kbs_parses_recorded_fixture() -> None:
    client = StaticHttpClient({"/data_day": load_fixture("kbs_bars.json")})
    provider = build_provider("kbs", client, _settings())
    bars = provider.get_daily_prices("VNM", START, END)
    assert len(bars) == 5
    assert bars[0].date == date(2024, 1, 2)
    assert bars[0].close == 101.0
    assert bars[0].source == "kbs"


def test_kbs_bad_schema_raises() -> None:
    client = StaticHttpClient({"/data_day": load_fixture("bad_schema.json")})
    provider = build_provider("kbs", client, _settings())
    with pytest.raises(SchemaError):
        provider.get_daily_prices("VNM", START, END)


def test_tcbs_constituents_parse() -> None:
    client = StaticHttpClient({"/index/constituents": load_fixture("tcbs_constituents.json")})
    provider = build_provider("tcbs", client, _settings())
    assert provider.get_index_constituents("VN30") == ["VNM", "FPT", "ACB"]


def test_kbs_lists_stock_symbols_and_filters_exchange() -> None:
    client = StaticHttpClient({"/stock/search/data": load_fixture("kbs_symbols.json")})
    provider = build_provider("kbs", client, _settings())
    listed = provider.list_symbols("")
    codes = {info.code for info in listed}
    assert {"VNM", "FPT", "SHS", "PVS", "ACV", "QNS"} <= codes
    assert "E1VFVN30" not in codes  # recorded row is type=fund, not a stock
    assert {info.exchange for info in listed} == {"HOSE", "HNX", "UPCOM"}
    assert {info.source for info in listed} == {"kbs"}

    hnx = provider.list_symbols("hnx")
    assert {info.code for info in hnx} == {"CEO", "IDC", "PVS", "SHS"}
    assert {info.exchange for info in hnx} == {"HNX"}


def test_kbs_index_constituents_map_canonical_codes_to_groups() -> None:
    client = StaticHttpClient(
        {
            "/index/30/stocks": load_fixture("kbs_index_vn30.json"),
            "/index/HOSE/stocks": load_fixture("kbs_index_hose.json"),
        }
    )
    provider = build_provider("kbs", client, _settings())
    vn30 = provider.get_index_constituents("VN30")
    assert len(vn30) == 30
    assert {"ACB", "VNM", "FPT"} <= set(vn30)
    vnindex = provider.get_index_constituents("VNINDEX")
    assert len(vnindex) == 412
    assert {"ACB", "VNM"} <= set(vnindex)


def test_kbs_index_constituents_unknown_group_raises() -> None:
    provider = build_provider("kbs", StaticHttpClient({}), _settings())
    with pytest.raises(EmptyResultError):
        provider.get_index_constituents("FOOINDEX")


def test_providers_declare_capability_flags() -> None:
    for provider_id in ("vci", "kbs", "dnse", "tcbs", "ssi_iboard"):
        provider = build_provider(provider_id, StaticHttpClient({}), _settings())
        assert provider.returns_adjusted_prices is False
        assert provider.supports_indexes is True
