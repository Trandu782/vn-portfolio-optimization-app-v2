"""The benchmark indices every sync keeps up to date.

Canonical codes are provider-neutral; each provider maps them to its own spelling
(see ``Provider.INDEX_MAP``). The codes are stored in ``indices_daily`` as-is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Benchmark:
    """A market index tracked as a benchmark."""

    code: str
    exchange: str
    name: str


BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark(code="VNINDEX", exchange="HOSE", name="VN-Index"),
    Benchmark(code="VN30", exchange="HOSE", name="VN30"),
    Benchmark(code="HNXINDEX", exchange="HNX", name="HNX-Index"),
    Benchmark(code="UPCOMINDEX", exchange="UPCoM", name="UPCoM-Index"),
)

#: Quick lookup of the benchmark for a canonical code.
BENCHMARK_BY_CODE = {benchmark.code: benchmark for benchmark in BENCHMARKS}
