"""Compare raw and adjusted prices around a corporate action for one symbol.

For every provider (plus the locally stored series) this prints the closes just
before and just after ``DATE`` and whether the provider's ``adj_close`` differs
from ``close``. If a provider adjusts for a dividend/split you will see a
non-zero ``adj %`` and an ``adj_move`` that differs from ``raw_move``.

Usage:
    python scripts/check_adjustment.py VNM 2024-05-03
    python scripts/check_adjustment.py VNM 2024-05-03 --window 15 --json

Result format (text table):
    provider  rows  adjusted  adj %   before / after (close/adj)     raw / adj move
    tcbs      21    no        0.00%   100.00/100.00 -> 95.00/95.00   -5.00% / -5.00%
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from data.context import DataContext
from data.errors import ProviderError
from data.models import PriceBar
from data.settings import get_settings


def _point(bar: PriceBar | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {"date": bar.date.isoformat(), "close": bar.close, "adj_close": bar.adj_close}


def _summarise(source: str, bars: list[PriceBar], target: date) -> dict[str, Any]:
    adjusted_days = [bar for bar in bars if abs(bar.adj_close - bar.close) > 1e-9]
    before = next((bar for bar in reversed(bars) if bar.date <= target), None)
    after = next((bar for bar in bars if bar.date >= target), None)
    raw_move = adj_move = None
    if before is not None and after is not None:
        if before.close:
            raw_move = (after.close - before.close) / before.close
        if before.adj_close:
            adj_move = (after.adj_close - before.adj_close) / before.adj_close
    max_adjustment = max(
        (abs(bar.adj_close - bar.close) / bar.close for bar in adjusted_days if bar.close),
        default=0.0,
    )
    return {
        "source": source,
        "rows": len(bars),
        "adjusted": bool(adjusted_days),
        "max_adjustment_pct": max_adjustment,
        "before": _point(before),
        "after": _point(after),
        "raw_move_pct": raw_move,
        "adj_move_pct": adj_move,
    }


def _print_row(summary: dict[str, Any]) -> None:
    before = summary["before"]
    after = summary["after"]
    point_before = f"{before['close']:.2f}/{before['adj_close']:.2f}" if before else "-"
    point_after = f"{after['close']:.2f}/{after['adj_close']:.2f}" if after else "-"
    raw_move = f"{summary['raw_move_pct']:.2%}" if summary["raw_move_pct"] is not None else "-"
    adj_move = f"{summary['adj_move_pct']:.2%}" if summary["adj_move_pct"] is not None else "-"
    print(
        f"{summary['source']:10} {summary['rows']:5} "
        f"{'yes' if summary['adjusted'] else 'no':8} "
        f"{summary['max_adjustment_pct']:.2%}  "
        f"{point_before:>22}  {point_after:>22}  {raw_move:>8}  {adj_move:>8}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare raw vs adjusted prices.")
    parser.add_argument("symbol")
    parser.add_argument("date", help="Corporate action date YYYY-MM-DD")
    parser.add_argument("--window", type=int, default=10, help="Calendar days each side.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch around the action date, compare raw vs adjusted, print the result."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    symbol = args.symbol.upper()
    target = date.fromisoformat(args.date)
    start = target - timedelta(days=args.window * 2)
    end = target + timedelta(days=args.window * 2)

    context = DataContext(get_settings())
    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, object]] = []
    for provider in context.providers:
        try:
            bars = provider.get_daily_prices(symbol, start, end)
        except ProviderError as exc:
            failures.append(
                {"source": provider.id, "error": str(exc), "error_type": exc.error_type}
            )
            continue
        summaries.append(_summarise(provider.id, bars, target))

    stored = context.service.get_prices(symbol, start=start, end=end, ensure=False)
    if stored.rows:
        summaries.append(_summarise("database", stored.rows, target))

    if args.json:
        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "action_date": target.isoformat(),
                    "window_days": args.window,
                    "sources": summaries,
                    "failures": failures,
                },
                indent=2,
            )
        )
    else:
        print(f"Symbol: {symbol}  action date: {target.isoformat()}  window: +/-{args.window} days")
        print(
            f"{'provider':10} {'rows':>5} {'adjusted':8} {'adj %':6}  "
            f"{'before(close/adj)':>22}  {'after(close/adj)':>22}  "
            f"{'raw_move':>8}  {'adj_move':>8}"
        )
        for summary in summaries:
            _print_row(summary)
        for failure in failures:
            print(f"{failure['source']:10} FAILED [{failure['error_type']}] {failure['error']}")
    return 0 if summaries else 1


if __name__ == "__main__":
    sys.exit(main())
