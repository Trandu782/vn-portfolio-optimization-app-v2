"""Probe every data provider and report success, latency, depth and adjustment.

Calls each registered provider for several tickers and one index over a five-year
range and prints a table (or JSON). Run it on the hosted environment to pick the
``PROVIDER_ORDER`` that actually works there, because an endpoint reachable from a
laptop may be blocked from the cloud and vice-versa.

Usage:
    python scripts/probe_providers.py
    python scripts/probe_providers.py --tickers VNM,FPT,ACB --index VNINDEX --years 5
    python scripts/probe_providers.py --json
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, timedelta

from data.context import DataContext
from data.probe import DEFAULT_INDEX, DEFAULT_TICKERS, run_probe
from data.settings import get_settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe VN market-data providers.")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--start", default=None, help="Override start date YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Override end date YYYY-MM-DD.")
    parser.add_argument("--json", action="store_true", help="Emit the raw JSON report.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and print the results."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=365 * args.years)
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]

    context = DataContext(get_settings())
    report = run_probe(
        context.providers, start=start, end=end, tickers=tickers, index_code=args.index
    )

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(
            f"Probe {start.isoformat()} .. {end.isoformat()}  "
            f"tickers={tickers} index={args.index}"
        )
        for probe in report.providers:
            print(f"\n[{probe.provider}] {'OK' if probe.ok else 'FAILED'}")
            for sample in probe.samples:
                if sample.ok:
                    latency = f"{sample.latency_ms:.0f}ms" if sample.latency_ms else "-"
                    adjusted = "yes" if sample.looks_adjusted else "no"
                    print(
                        f"  {sample.label:10} ok  {latency:>8}  rows={sample.rows:<4} "
                        f"{sample.first_date}..{sample.last_date} "
                        f"depth={sample.history_depth_days}d adjusted={adjusted}"
                    )
                else:
                    print(
                        f"  {sample.label:10} FAIL [{sample.error_type}] {sample.error}"
                    )
        recommended = ",".join(report.recommended_order) or "(none worked)"
        print(f"\nrecommended PROVIDER_ORDER={recommended}")
    return 0 if report.recommended_order else 1


if __name__ == "__main__":
    sys.exit(main())
