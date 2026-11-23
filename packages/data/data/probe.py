"""Probe providers and recommend a failover order.

``run_probe`` calls every provider for the given tickers and one index over a
date range, reporting success, latency, rows, history depth and whether prices
look adjusted. It is used by ``scripts/probe_providers.py`` and the protected
``GET /api/v1/data/probe`` endpoint so the provider order can be set from what
works on the *hosted* network, not just a developer laptop.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from functools import partial

from data.errors import ProviderError
from data.interfaces import DataProvider
from data.models import PriceBar, ProbeReport, ProbeSample, ProviderProbe

DEFAULT_TICKERS: tuple[str, ...] = ("VNM", "FPT", "ACB")
DEFAULT_INDEX = "VNINDEX"


def _sample(
    provider: DataProvider, label: str, fetch: Callable[[], list[PriceBar]]
) -> ProbeSample:
    """Probe one symbol/index and capture timing and shape information."""
    began = time.monotonic()
    try:
        bars = fetch()
    except ProviderError as exc:
        return ProbeSample(label=label, ok=False, error=str(exc), error_type=exc.error_type)
    except Exception as exc:
        return ProbeSample(
            label=label, ok=False, error=f"{type(exc).__name__}: {exc}", error_type="unexpected"
        )
    latency = (time.monotonic() - began) * 1000.0
    if not bars:
        return ProbeSample(
            label=label, ok=False, latency_ms=latency, error="no rows", error_type="empty"
        )
    first, last = bars[0].date, bars[-1].date
    looks_adjusted = provider.returns_adjusted_prices and any(
        abs(bar.adj_close - bar.close) > 1e-9 for bar in bars
    )
    return ProbeSample(
        label=label,
        ok=True,
        latency_ms=latency,
        rows=len(bars),
        first_date=first,
        last_date=last,
        history_depth_days=(last - first).days,
        looks_adjusted=looks_adjusted,
    )


def run_probe(
    providers: Sequence[DataProvider],
    *,
    start: date,
    end: date,
    tickers: Sequence[str] = DEFAULT_TICKERS,
    index_code: str = DEFAULT_INDEX,
) -> ProbeReport:
    """Probe every provider and return a report with a recommended order."""
    probes: list[ProviderProbe] = []
    latencies: dict[str, list[float]] = {}
    for provider in providers:
        samples = [
            _sample(
                provider,
                ticker.upper(),
                partial(provider.get_daily_prices, ticker.upper(), start, end),
            )
            for ticker in tickers
        ]
        if provider.supports_indexes:
            samples.append(
                _sample(
                    provider,
                    index_code.upper(),
                    partial(provider.get_index_daily, index_code.upper(), start, end),
                )
            )
        ok = any(sample.ok for sample in samples)
        probes.append(ProviderProbe(provider=provider.id, ok=ok, samples=samples))
        latencies[provider.id] = [
            sample.latency_ms
            for sample in samples
            if sample.ok and sample.latency_ms is not None
        ]

    def mean_latency(provider_id: str) -> float:
        values = latencies.get(provider_id, [])
        return sum(values) / len(values) if values else float("inf")

    working = [probe for probe in probes if probe.ok]
    recommended = [
        probe.provider for probe in sorted(working, key=lambda p: mean_latency(p.provider))
    ]
    return ProbeReport(
        generated_at=datetime.now(UTC),
        tickers=[ticker.upper() for ticker in tickers],
        index_code=index_code.upper(),
        start=start,
        end=end,
        providers=probes,
        recommended_order=recommended,
    )
