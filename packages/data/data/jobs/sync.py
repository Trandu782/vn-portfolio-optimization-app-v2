"""Manual developer sync: ``python -m data.jobs.sync``.

The scheduled production path is the protected ``POST /api/v1/data/refresh``
endpoint driven by Vercel Cron; this CLI is for local/backfill work and uses the
same :class:`~data.sync.SyncService` so behaviour is identical.

Usage:
    python -m data.jobs.sync --backfill VNM --backfill FPT --backfill ACB --benchmarks
    python -m data.jobs.sync --symbols VNM,FPT --benchmarks
    python -m data.jobs.sync --benchmarks
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from data.context import DataContext
from data.db.base import create_all
from data.settings import get_settings
from data.sync import SymbolSyncResult


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m data.jobs.sync",
        description="Incremental VN market data sync (manual developer command).",
    )
    parser.add_argument(
        "--backfill",
        action="append",
        default=[],
        metavar="SYMBOL",
        help="Backfill a symbol's full bounded history (repeatable).",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols to sync incrementally.",
    )
    parser.add_argument(
        "--benchmarks",
        action="store_true",
        help="Sync VN-Index, VN30, HNX-Index and UPCoM-Index.",
    )
    parser.add_argument(
        "--reference",
        action="store_true",
        help=(
            "Fill empty symbol and index-constituent tables (live providers first, "
            "then the built-in seed)."
        ),
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=None,
        help="History window in days for a fresh backfill (default from settings).",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create tables directly (local dev only; production uses Alembic).",
    )
    return parser


def _print_result(result: SymbolSyncResult) -> None:
    state = "ok" if result.ok else "FAIL"
    print(
        f"[{state}] {result.kind}:{result.symbol} {result.status} "
        f"provider={result.provider or '-'} rows={result.rows}"
    )
    if result.message:
        print(f"    {result.message}")
    for warning in result.warnings:
        print(f"    warning: {warning}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sync selected by the CLI arguments."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    context = DataContext(settings)
    if args.create_schema:
        create_all(context.engine)

    results: list[SymbolSyncResult] = []
    if args.reference:
        reference = context.sync.sync_reference_data()
        print(
            f"[ok] reference symbols={reference.symbols} "
            f"source={reference.symbol_source or '-'}"
        )
        for code in reference.constituents:
            source = reference.constituent_sources.get(code, "-")
            print(f"    {code}: {reference.constituents[code]} members (source={source})")
        for warning in reference.warnings:
            print(f"    warning: {warning}")
    for symbol in [item.upper() for item in args.backfill]:
        results.append(
            context.sync.sync_symbol(
                symbol, history_days=args.history_days, force_full=True
            )
        )
    incremental = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    for symbol in incremental:
        results.append(context.sync.sync_symbol(symbol, history_days=args.history_days))

    if args.benchmarks or not (args.backfill or incremental or args.reference):
        results.extend(context.sync.sync_benchmarks(history_days=args.history_days))

    for result in results:
        _print_result(result)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
