"""Manual precompute command: ``python -m data.v2.jobs.precompute``.

The scheduled production path is the manual ``.github/workflows/precompute_v2.yml``
job (a runner, not a short serverless function); this CLI is the local / manual
equivalent and drives the same :class:`~data.v2.precompute.V2PrecomputeService`.

Usage:
    python -m data.v2.jobs.precompute --incremental
    python -m data.v2.jobs.precompute --full --start 2023-01-01 --limit 50
    python -m data.v2.jobs.precompute --incremental --create-schema
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from data.db.base import create_all, create_engine_for, create_session_factory
from data.settings import get_settings
from data.v2.context import V2DataContext
from data.v2.precompute import (
    V2PrecomputeService,
    recompute_adjustment_flags_offline,
    sources_from_context,
)
from data.v2.precompute_schemas import PrecomputeReport


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m data.v2.jobs.precompute",
        description="Resumable V2 precompute pipeline (manual command).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--incremental", action="store_true", help="Fetch only new dates (default)."
    )
    mode.add_argument(
        "--full", action="store_true", help="Re-fetch the whole backfill window."
    )
    parser.add_argument("--start", default=None, metavar="YYYY-MM-DD", help="Backfill start.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Max tickers for the price/profile steps."
    )
    parser.add_argument(
        "--profiles",
        action="store_true",
        help=(
            "Force a market-cap / corporate-action refresh and re-check the "
            "known-empty symbols an incremental run skips."
        ),
    )
    parser.add_argument(
        "--members",
        choices=("VN30", "VN100"),
        default=None,
        metavar="{VN30,VN100}",
        help=(
            "Restrict the price/profile/liquidity/quality/flag steps to one index's "
            "members (master/membership/benchmarks stay full-universe)."
        ),
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create tables directly (local dev only; production uses Alembic).",
    )
    parser.add_argument(
        "--recompute-flags",
        action="store_true",
        help=(
            "Recompute only the adjustment-quality flags from the stored prices and "
            "corporate actions (no network, no price re-download). Requires --members."
        ),
    )
    return parser


def _print_report(report: PrecomputeReport) -> None:
    status = "ok" if report.ok else "FAIL"
    print(f"[{status}] mode={report.mode} as_of={report.as_of.isoformat()}")
    print(
        f"    coverage: covered={report.coverage.covered} missing={report.coverage.missing}"
    )
    for step in report.steps:
        state = "ok" if step.ok else "FAIL"
        detail = f" {step.message}" if step.message else ""
        print(f"    [{state}] {step.name}: processed={step.processed}{detail}")
    print(f"    quality_errors={report.quality_errors}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pipeline selected by the CLI arguments."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    recompute_members: str | None = None
    if args.recompute_flags:
        if args.members is None:
            print("--recompute-flags requires --members {VN30,VN100}", file=sys.stderr)
            return 2
        recompute_members = args.members
    start: date | None = None
    if args.start:
        try:
            start = date.fromisoformat(args.start)
        except ValueError:
            print(f"invalid --start date: {args.start!r} (expected YYYY-MM-DD)", file=sys.stderr)
            return 2

    settings = get_settings()
    engine = create_engine_for(settings.database_url)
    try:
        if args.create_schema:
            create_all(engine)
        session_factory = create_session_factory(engine)
        if recompute_members is not None:
            # Offline path: recompute the flags from stored data only, no network.
            report = recompute_adjustment_flags_offline(
                session_factory, members=recompute_members
            )
        else:
            context = V2DataContext()
            service = V2PrecomputeService(
                session_factory=session_factory,
                sources=sources_from_context(context),
            )
            report = service.run(
                mode="full" if args.full else "incremental",
                start=start,
                limit=args.limit,
                profiles=True if args.profiles else None,
                members=args.members,
            )
    finally:
        engine.dispose()

    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
