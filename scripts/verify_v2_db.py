"""Print a readiness summary for the local V2 precompute database (vnopt.db).

Read-only: opens the configured database and prints the counts the Optimize
filter and the Sector tab depend on. Run from the repo root:

    python scripts/verify_v2_db.py

Assumes the packages are installed (``make install``); ``DATABASE_URL`` defaults
to the repo-root SQLite file, so no environment variable is required.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from data.db.base import create_engine_for, create_session_factory, session_scope
from data.settings import get_settings
from data.v2.analytics.liquidity import DEFAULT_PRESET_ID, filter_universe
from data.v2.analytics.universe_reader import flags_policy_current, load_universe_snapshot
from data.v2.reader import sector_coverage
from data.v2.store import V2Store

#: Additive V2 tables (V1 tables and benchmarks are handled separately).
V2_TABLES = (
    "v2_ticker_master",
    "v2_sector_map",
    "v2_index_membership",
    "v2_daily_prices",
    "v2_liquidity",
    "v2_market_cap",
    "v2_corporate_actions",
    "v2_adjustment_flags",
    "v2_progress",
)


def _human_size(num_bytes: int) -> str:
    """Return a compact human-readable byte size."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def _database_size(engine) -> tuple[str, int]:
    """Return the database file path and its size (0 for a non-file database)."""
    database = engine.url.database
    if not database:
        return "", 0
    path = Path(database)
    if not path.exists():
        return str(path), 0
    return str(path), path.stat().st_size


def main() -> int:
    settings = get_settings()
    engine = create_engine_for(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        with session_scope(session_factory) as session:
            store = V2Store(session)
            priced = len(store.history_starts())
            flags = store.list_adjustment_flags()
            flagged = sum(1 for flag in flags if flag.flagged)
            excluded = sum(1 for flag in flags if flag.exclude_from_group_indices)
            flagged_included = sum(
                1 for flag in flags if flag.flagged and not flag.exclude_from_group_indices
            )
            excluded_tickers = [flag.ticker for flag in flags if flag.exclude_from_group_indices]
            policy_current = flags_policy_current(flags)
            market_caps = len(store.list_market_cap())
            latest_price = store.overall_latest_price_date()
            min_date, max_date = session.execute(
                text("SELECT MIN(date), MAX(date) FROM v2_daily_prices")
            ).one()
            data_as_of = session.scalar(
                text(
                    "SELECT MAX(d.data_as_of) FROM ("
                    " SELECT data_as_of FROM v2_ticker_master UNION ALL"
                    " SELECT data_as_of FROM v2_daily_prices UNION ALL"
                    " SELECT data_as_of FROM v2_liquidity UNION ALL"
                    " SELECT data_as_of FROM v2_market_cap UNION ALL"
                    " SELECT data_as_of FROM v2_corporate_actions UNION ALL"
                    " SELECT data_as_of FROM v2_adjustment_flags) AS d"
                )
            )
            benchmark_rows = session.execute(
                text(
                    "SELECT index_code, COUNT(*) AS n FROM indices_daily"
                    " GROUP BY index_code ORDER BY index_code"
                )
            ).all()
            vn100_priced = session.scalar(
                text(
                    "SELECT COUNT(DISTINCT p.symbol_code) FROM v2_index_membership m"
                    " JOIN v2_daily_prices p ON p.symbol_code = m.symbol_code"
                    " WHERE m.index_code = 'VN100'"
                )
            )
            unfinished = session.execute(
                text(
                    "SELECT kind, symbol, state, last_date FROM v2_progress"
                    " WHERE state <> 'done' ORDER BY kind, symbol"
                )
            ).all()
            row_counts = session.execute(
                text(
                    " UNION ALL ".join(
                        f"SELECT '{table}' AS tbl, COUNT(*) AS n FROM {table}"
                        for table in V2_TABLES
                    )
                )
            ).all()

        coverage = sector_coverage(session_factory)
        snapshot = load_universe_snapshot(session_factory)
        passing = filter_universe(snapshot.rows, DEFAULT_PRESET_ID).kept
        by_sector: dict[str, int] = {}
        for row in passing:
            if row.sector:
                by_sector[row.sector] = by_sector.get(row.sector, 0) + 1
        sectors_ge3 = sorted(name for name, count in by_sector.items() if count >= 3)

        db_path, db_size = _database_size(engine)

        print(f"database                  : {settings.database_url}")
        print(f"database file             : {db_path}")
        print(f"database file size        : {_human_size(db_size)} ({db_size} bytes)")
        print("row counts per table      :")
        for table, count in row_counts:
            print(f"  {table:<24} {count}")
        print(f"tickers with prices       : {priced}")
        print(f"VN100 members with prices : {vn100_priced}")
        print(f"sector coverage           : {coverage.covered} covered, {coverage.missing} missing")
        print(f"market-cap coverage       : {market_caps} (of {priced} priced tickers)")
        print(f"benchmark bars            : {dict(benchmark_rows)}")
        print(f"price date range          : {min_date} .. {max_date}")
        print(
            f"adjustment flags          : {len(flags)} rows "
            f"({flagged} flagged, {excluded} excluded, "
            f"{flagged_included} flagged but included)"
        )
        print(
            "excluded tickers          : "
            + (", ".join(excluded_tickers) if excluded_tickers else "(none)")
        )
        print(f"flags policy current      : {'yes' if policy_current else 'no'}")
        print(f"latest price date         : {latest_price}")
        print(f"latest data_as_of         : {data_as_of}")
        print(f"unfinished progress rows  : {len(unfinished)}")
        for kind, symbol, state, last_date in unfinished:
            print(f"  {kind}/{symbol}: {state} (last {last_date})")
        print(f"sectors >=3 passing {DEFAULT_PRESET_ID}: {len(sectors_ge3)}")
        for name in sectors_ge3:
            print(f"  - {name}: {by_sector[name]} tickers")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
