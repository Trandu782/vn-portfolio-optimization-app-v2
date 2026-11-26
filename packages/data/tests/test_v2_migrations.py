"""Alembic migrations 0001-0005 upgrade/downgrade cleanly on SQLite.

Runs the real migration chain against a throwaway SQLite database via the Alembic
command API (no network), asserts every V2 table exists at ``head``, then steps
back down one revision at a time and asserts each migration's tables/columns are
removed. The settings module is monkeypatched so ``alembic/env.py`` (which reads
``data.settings.get_settings().database_url``) targets the temporary file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from data.settings import DataSettings, get_settings

_PACKAGES_DATA = Path(__file__).resolve().parents[1]
_INI = _PACKAGES_DATA / "alembic.ini"

EXPECTED_TABLES = {
    "alembic_version",
    "symbols",
    "prices_daily",
    "indices_daily",
    "index_constituents",
    "sync_log",
    "corporate_actions",
    "v2_ticker_master",
    "v2_sector_map",
    "v2_index_membership",
    "v2_daily_prices",
    "v2_liquidity",
    "v2_market_cap",
    "v2_corporate_actions",
    "v2_progress",
    "v2_adjustment_flags",
    "v2_financial_ratios",
    "v2_sector_statistics",
}

#: (revision_to_downgrade_to, tables_that_migration created and must now be gone).
_REV_DOWN: tuple[tuple[str, set[str]], ...] = (
    ("0004_v2_adjustment_flag_anomalies", {"v2_financial_ratios", "v2_sector_statistics"}),
    ("0003_v2_adjustment_flags", set()),  # 0004 only drops the anomalies column
    ("0002_v2_precompute", {"v2_adjustment_flags"}),
    ("0001_initial", {"v2_ticker_master", "v2_sector_map"}),
    (None, {"symbols", "prices_daily", "v2_progress"}),  # back to base
)


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    settings = DataSettings(database_url=url)
    monkeypatch.setattr("data.settings.get_settings", lambda: settings)
    # Bypass any cached settings instance the process already built.
    get_settings.cache_clear()
    config = Config(str(_INI))
    config.set_main_option("sqlalchemy.url", url)
    config.set_main_option("script_location", str(_PACKAGES_DATA / "alembic"))
    yield config


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_to_head_creates_every_table(
    alembic_config: Config, tmp_path: Path
) -> None:
    command.upgrade(alembic_config, "head")
    tables = _table_names(f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}")
    assert tables >= EXPECTED_TABLES, f"missing {sorted(EXPECTED_TABLES - tables)}"


def test_downgrade_removes_each_revisions_tables(
    alembic_config: Config, tmp_path: Path
) -> None:
    command.upgrade(alembic_config, "head")
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    for revision, introduced in _REV_DOWN:
        if revision is None:
            command.downgrade(alembic_config, "base")
        else:
            command.downgrade(alembic_config, revision)
        tables = _table_names(url)
        for table in introduced:
            assert table not in tables, f"{table} still present after {revision}"
    # Back at base there should be no business tables left.
    tables = _table_names(url)
    assert "alembic_version" in tables
    assert not (tables & {"symbols", "v2_ticker_master", "v2_adjustment_flags"})


def test_downgrade_0004_drops_the_anomalies_column(
    alembic_config: Config, tmp_path: Path
) -> None:
    command.upgrade(alembic_config, "head")
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    engine = create_engine(url)
    try:
        assert "anomalies" in {
            column["name"] for column in inspect(engine).get_columns("v2_adjustment_flags")
        }
    finally:
        engine.dispose()
    command.downgrade(alembic_config, "0003_v2_adjustment_flags")
    engine = create_engine(url)
    try:
        assert "anomalies" not in {
            column["name"] for column in inspect(engine).get_columns("v2_adjustment_flags")
        }
    finally:
        engine.dispose()


def test_round_trip_upgrade_downgrade_upgrade_is_stable(
    alembic_config: Config, tmp_path: Path
) -> None:
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    tables = _table_names(url)
    assert tables >= EXPECTED_TABLES


def test_0006_v2_query_indexes_upgrade_and_downgrade(
    alembic_config: Config, tmp_path: Path
) -> None:
    """Migration 0006 creates and cleanly drops query-performance indexes."""
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    command.upgrade(alembic_config, "head")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        price_indexes = {idx["name"] for idx in insp.get_indexes("v2_daily_prices")}
        ratio_indexes = {idx["name"] for idx in insp.get_indexes("v2_financial_ratios")}
    finally:
        engine.dispose()
    assert "ix_v2_daily_prices_date" in price_indexes
    assert "ix_v2_financial_ratios_period" in ratio_indexes

    command.downgrade(alembic_config, "-1")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        price_indexes_after = {idx["name"] for idx in insp.get_indexes("v2_daily_prices")}
        ratio_indexes_after = {idx["name"] for idx in insp.get_indexes("v2_financial_ratios")}
    finally:
        engine.dispose()
    assert "ix_v2_daily_prices_date" not in price_indexes_after
    assert "ix_v2_financial_ratios_period" not in ratio_indexes_after


def test_v2_progress_state_column_supports_pre_screen_rejected(
    alembic_config: Config, tmp_path: Path
) -> None:
    """v2_progress.state must be at least 32 chars for 'pre_screen_rejected' (19 chars)."""
    from data.db.models import V2Progress

    assert V2Progress.__table__.c.state.type.length >= 32  # type: ignore[attr-defined]
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    command.upgrade(alembic_config, "head")
    engine = create_engine(url)
    try:
        cols = {col["name"]: col for col in inspect(engine).get_columns("v2_progress")}
        assert cols["state"]["type"].length >= 32
    finally:
        engine.dispose()


