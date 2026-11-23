"""Tests for curated presets and their on-demand constituent resolution."""

from __future__ import annotations

from data.context import DataContext
from data.db.base import create_all
from data.offline import StaticHttpClient
from data.presets import INDEX_PRESETS, PRESET_BY_CODE
from data.seed import seed_constituents
from data.settings import DataSettings


def test_presets_include_vn30() -> None:
    assert [preset.code for preset in INDEX_PRESETS] == ["VN30"]
    assert "VN30" in PRESET_BY_CODE


def test_get_index_constituents_falls_back_to_seed(tmp_path) -> None:
    settings = DataSettings(
        database_url=f"sqlite:///{tmp_path / 'presets.db'}",
        provider_order="kbs",
    )
    context = DataContext(settings, http=StaticHttpClient({}))
    create_all(context.engine)
    try:
        members = context.service.get_index_constituents("VN30")
        assert members
        assert set(members) == set(seed_constituents("VN30"))
    finally:
        context.engine.dispose()
