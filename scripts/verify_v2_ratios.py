"""Print a readiness summary for the stored V2b fundamental ratios.

Read-only: opens the configured database (the repo-root ``vnopt.db`` by default)
and prints the counts the Fundamentals tab will rely on. Run from the repo root:

    python scripts/verify_v2_ratios.py

Assumes the packages are installed and migration ``0005`` is applied.
"""

from __future__ import annotations

from datetime import date

from data.db.base import create_engine_for, create_session_factory, session_scope
from data.settings import get_settings
from data.v2.ratio_verify import RatioVerification, summarize_ratios
from data.v2.store import V2Store


def _print_summary(summary: RatioVerification, database_url: str) -> None:
    """Print every section the Fundamentals readiness check needs."""
    print(f"database                  : {database_url}")
    print(f"tickers with ratios       : {len(summary.tickers_with_ratios)}")
    print(f"  {', '.join(summary.tickers_with_ratios) or '(none)'}")
    print(
        f"latest period per ticker  : min {summary.latest_min} .. max {summary.latest_max}"
    )
    print("tickers per latest period :")
    for period, count in sorted(summary.latest_period_counts.items()):
        print(f"  {period}  {count}")
    print("group counts (tickers)    :")
    for group, count in summary.group_tickers.items():
        print(f"  {group:<12} {count}")
    print(f"v2_sector_statistics rows : {summary.sector_statistic_rows}")
    print(
        f"sectors with peers >= {summary.min_peers}: "
        f"{len(summary.sectors_with_enough_peers)} of {len(summary.sector_peer_counts)}"
    )
    for sector, count in summary.sector_peer_counts.items():
        marker = "ok" if count >= summary.min_peers else "low"
        print(f"  {sector:<28} N={count:<4} {marker}")
    print("null share by group (latest period only):")
    for group, shares in summary.null_share_latest_by_group.items():
        print(f"  [{group}] N={summary.group_tickers.get(group, 0)}")
        for ratio, share in shares.items():
            print(f"    {ratio:<20} {share * 100:5.1f}% null")
    print("null share by group and period_type:")
    for group, by_type in summary.null_share_by_period_type.items():
        row_counts = summary.period_type_counts.get(group, {})
        for period_type, shares in by_type.items():
            print(f"  [{group}/{period_type}] n={row_counts.get(period_type, 0)}")
            for ratio, share in shares.items():
                print(f"    {ratio:<20} {share * 100:5.1f}% null")
    print("ratio quality warnings    :")
    if summary.quality_warning_counts:
        for check, count in summary.quality_warning_counts.items():
            print(f"  {check:<16} {count}")
    else:
        print("  (none)")
    print(
        f"tickers without ratios    : {len(summary.tickers_without_ratios)}"
        + (
            f" ({', '.join(summary.tickers_without_ratios[:30])}"
            + (", ..." if len(summary.tickers_without_ratios) > 30 else "")
            + ")"
            if summary.tickers_without_ratios
            else ""
        )
    )


def main() -> int:
    """Load the stored ratio records and print the readiness summary."""
    settings = get_settings()
    engine = create_engine_for(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        with session_scope(session_factory) as session:
            store = V2Store(session)
            records = store.list_ratios()
            statistics = store.list_sector_statistics()
            master = [record.ticker for record in store.list_ticker_master()]
            sector_by_ticker = {
                row.ticker.strip().upper(): row.icb_level2_name
                for row in store.list_sectors()
                if row.icb_level2_name
            }
        as_of = max((record.data_as_of for record in records), default=date.today())
        summary = summarize_ratios(
            records,
            statistics,
            master=master,
            sector_by_ticker=sector_by_ticker,
            as_of=as_of,
        )
        _print_summary(summary, settings.database_url)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
