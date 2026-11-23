"""Risk routes: the metric catalogue, the benchmark list and a full analysis.

The routes are thin. ``POST /risk`` resolves the requested symbols through the
data service (backfilling on demand), reuses ``core.universe.build_universe`` to
assemble the aligned returns matrix, loads and aligns the selected benchmark
index, then calls ``core.risk.compute_risk``. Every option list is published from
the core registry so the UI renders it without hardcoding.

Errors map to 422 with a clear message: an unknown metric or benchmark, no usable
price data, or a metric whose inputs are degenerate (for example a benchmark with
zero variance for beta).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.api.v1.data import get_data_service
from app.api.v1.schemas import Assumptions, assumptions_from
from app.api.v1.universe import _load_symbol_series
from core.registry import Registry
from core.risk import (
    DEFAULT_CONFIDENCE,
    Performance,
    aligned_benchmark_returns,
    compute_benchmark_risk,
    compute_risk,
    risk_metrics,
    sharpe_ratio,
)
from core.settings import UserSettings
from core.universe import build_universe
from data.benchmarks import BENCHMARK_BY_CODE, BENCHMARKS
from data.service import DataService

router = APIRouter(tags=["risk"])

#: Benchmark preselected by the UI when the user has not chosen one.
DEFAULT_BENCHMARK = "VNINDEX"


class SharpeRequest(BaseModel):
    """Inputs for the Sharpe ratio calculation. Settings default when omitted."""

    mean_return: float = Field(
        ..., description="Expected annual return as a fraction (0.10 == 10%)."
    )
    volatility: float = Field(
        ..., description="Annualized volatility as a fraction (0.20 == 20%)."
    )
    settings: UserSettings | None = Field(
        default=None,
        description="User settings. Defaults apply when omitted.",
    )


class SharpeResponse(BaseModel):
    """Sharpe ratio and the settings used to compute it."""

    sharpe: float
    assumptions: Assumptions


class OptionResponse(BaseModel):
    """Registry metadata for one risk metric."""

    id: str
    name: str
    description: str
    parameter_schema: dict[str, Any] | None


class BenchmarkOption(BaseModel):
    """A benchmark index the user can compare the portfolio against."""

    code: str
    name: str
    exchange: str


class RiskDefaults(BaseModel):
    """Defaults the UI should preselect."""

    benchmark: str
    confidence: float


class RiskOptionsResponse(BaseModel):
    """Every risk metric and benchmark, published for the UI to render."""

    metrics: list[OptionResponse]
    benchmarks: list[BenchmarkOption]
    defaults: RiskDefaults


class RiskRequest(BaseModel):
    """Inputs for one risk analysis.

    ``symbols`` and the date range describe the analysed universe; ``weights`` is
    the portfolio (the current or the optimized one) measured against it.
    """

    weights: dict[str, float] = Field(
        default_factory=dict,
        description="Portfolio weight per symbol (fractions; cash is the remainder).",
    )
    symbols: list[str] = Field(
        default_factory=list, description="Universe tickers to analyse."
    )
    start: date
    end: date
    benchmark: str = Field(
        default=DEFAULT_BENCHMARK,
        description="Benchmark index code (VNINDEX, VN30, HNXINDEX, UPCOMINDEX).",
    )
    metrics: list[str] = Field(
        default_factory=list, description="Metric ids; empty computes every metric."
    )
    metric_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    settings: UserSettings | None = Field(
        default=None,
        description="User settings (risk-free rate). Defaults apply when omitted.",
    )


class PerformanceResponse(BaseModel):
    """Growth of 100 over the window with the headline return statistics."""

    dates: list[str]
    growth: list[float]
    total_return: float
    annualized_return: float
    max_drawdown: float


class RiskResponse(BaseModel):
    """Every selected metric's payload plus the growth series and the catalogue."""

    symbols: list[str]
    weights: dict[str, float]
    benchmark: str
    metrics: dict[str, Any]
    performance: PerformanceResponse
    assumptions: Assumptions
    options: list[OptionResponse]
    warnings: list[str] = Field(default_factory=list)


class ComparePortfolioBlock(BaseModel):
    """One portfolio's weights, metrics and growth series in the comparison."""

    weights: dict[str, float]
    metrics: dict[str, Any]
    performance: PerformanceResponse


class RiskCompareRequest(BaseModel):
    """Inputs for the side-by-side risk comparison on the Risk page.

    ``symbols`` and the date range describe the shared universe; the optional
    weight sets are projected onto it. Equal weight is computed server-side and
    the benchmark is measured as a one-asset portfolio.
    """

    symbols: list[str] = Field(
        default_factory=list, description="Shared universe tickers to analyse."
    )
    start: date
    end: date
    benchmark: str = Field(
        default=DEFAULT_BENCHMARK,
        description="Benchmark index code (VNINDEX, VN30, HNXINDEX, UPCOMINDEX).",
    )
    metrics: list[str] = Field(
        default_factory=list, description="Metric ids; empty computes every metric."
    )
    metric_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    current_weights: dict[str, float] | None = Field(
        default=None, description="Current portfolio weights (fractions of holdings)."
    )
    optimized_weights: dict[str, float] | None = Field(
        default=None, description="Chosen optimized portfolio weights (fractions)."
    )
    settings: UserSettings | None = Field(
        default=None,
        description="User settings (risk-free rate). Defaults apply when omitted.",
    )


class RiskCompareResponse(BaseModel):
    """Current, optimized, equal-weight and benchmark compared on one universe."""

    symbols: list[str]
    dates: list[str]
    benchmark: str
    current: ComparePortfolioBlock | None
    optimized: ComparePortfolioBlock | None
    equal_weight: ComparePortfolioBlock
    benchmark_portfolio: ComparePortfolioBlock
    options: list[OptionResponse]
    assumptions: Assumptions
    warnings: list[str] = Field(default_factory=list)


def _describe(registry: Registry[Any]) -> list[OptionResponse]:
    """Convert a registry's ``describe()`` output into API options."""
    return [
        OptionResponse(
            id=info.id,
            name=info.name,
            description=info.description,
            parameter_schema=info.parameter_schema,
        )
        for info in registry.describe()
    ]


def _dedupe(symbols: list[str]) -> list[str]:
    """Return the trimmed, upper-cased symbols without duplicates."""
    codes: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        code = raw.strip().upper()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _performance(performance: Performance) -> PerformanceResponse:
    """Convert a core performance result into the API response model."""
    return PerformanceResponse(
        dates=list(performance.dates),
        growth=list(performance.growth),
        total_return=performance.total_return,
        annualized_return=performance.annualized_return,
        max_drawdown=performance.max_drawdown,
    )


# -- routes -------------------------------------------------------------------


def _benchmark_options() -> list[BenchmarkOption]:
    """Return the benchmark catalogue from the data layer's canonical indices."""
    return [
        BenchmarkOption(code=item.code, name=item.name, exchange=item.exchange)
        for item in BENCHMARKS
    ]


@router.get("/risk/options", response_model=RiskOptionsResponse)
def read_risk_options() -> RiskOptionsResponse:
    """Publish every risk metric, the benchmark list and the defaults."""
    return RiskOptionsResponse(
        metrics=_describe(risk_metrics),
        benchmarks=_benchmark_options(),
        defaults=RiskDefaults(
            benchmark=DEFAULT_BENCHMARK, confidence=DEFAULT_CONFIDENCE
        ),
    )


@router.post("/risk", response_model=RiskResponse)
def analyse_risk(
    request: RiskRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> RiskResponse:
    """Compute the selected risk metrics for one portfolio over the universe."""
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    codes = _dedupe(request.symbols)
    if not codes:
        raise HTTPException(status_code=422, detail="provide at least one symbol")
    benchmark = request.benchmark.strip().upper()
    if benchmark not in BENCHMARK_BY_CODE:
        raise HTTPException(status_code=422, detail=f"unknown benchmark {benchmark!r}")

    series = [
        _load_symbol_series(service, code, request.start, request.end) for code in codes
    ]
    universe = build_universe(series, [], request.start, request.end)
    if not universe.symbols:
        raise HTTPException(
            status_code=422,
            detail="no price data available for the requested symbols",
        )

    index_series = service.get_index_prices(
        benchmark, start=request.start, end=request.end
    )
    if not index_series.rows:
        raise HTTPException(
            status_code=422,
            detail=f"no price data available for benchmark {benchmark!r}",
        )
    benchmark_returns = aligned_benchmark_returns(
        universe.returns_dates,
        [row.date for row in index_series.rows],
        [row.adj_close for row in index_series.rows],
    )
    settings = request.settings or UserSettings()

    try:
        report = compute_risk(
            symbols=universe.symbols,
            dates=universe.returns_dates,
            returns=universe.returns_matrix,
            benchmark_returns=benchmark_returns,
            weights=request.weights,
            risk_free_rate=settings.risk_free_rate,
            metric_ids=request.metrics or None,
            metric_params=request.metric_params or None,
        )
    except KeyError as exc:
        identifier = exc.args[0] if exc.args else "?"
        raise HTTPException(status_code=422, detail=f"unknown id {identifier!r}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid parameters: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    known = set(report.symbols)
    ignored = sorted(
        code for code in request.weights if code.strip().upper() not in known
    )
    warnings = [f"{item.code} dropped: {item.reason}" for item in universe.dropped]
    warnings.extend(
        f"weight ignored for {code}: not in the analysed universe" for code in ignored
    )

    return RiskResponse(
        symbols=list(report.symbols),
        weights=dict(report.weights),
        benchmark=benchmark,
        metrics=dict(report.metrics),
        performance=_performance(report.performance),
        assumptions=assumptions_from(settings),
        options=_describe(risk_metrics),
        warnings=warnings,
    )


@router.post("/risk/compare", response_model=RiskCompareResponse)
def compare_risk(
    request: RiskCompareRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> RiskCompareResponse:
    """Compare the current, optimized, equal-weight and benchmark portfolios.

    Every portfolio is measured on the same universe and window: one build of the
    returns matrix plus one aligned benchmark series. Equal weight is one over the
    number of kept tickers; the benchmark is analysed as a one-asset portfolio.
    """
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    codes = _dedupe(request.symbols)
    if not codes:
        raise HTTPException(status_code=422, detail="provide at least one symbol")
    benchmark = request.benchmark.strip().upper()
    if benchmark not in BENCHMARK_BY_CODE:
        raise HTTPException(status_code=422, detail=f"unknown benchmark {benchmark!r}")
    settings = request.settings or UserSettings()

    series = [
        _load_symbol_series(service, code, request.start, request.end) for code in codes
    ]
    universe = build_universe(series, [], request.start, request.end)
    if not universe.symbols:
        raise HTTPException(
            status_code=422,
            detail="no price data available for the requested symbols",
        )

    index_series = service.get_index_prices(
        benchmark, start=request.start, end=request.end
    )
    if not index_series.rows:
        raise HTTPException(
            status_code=422,
            detail=f"no price data available for benchmark {benchmark!r}",
        )
    benchmark_returns = aligned_benchmark_returns(
        universe.returns_dates,
        [row.date for row in index_series.rows],
        [row.adj_close for row in index_series.rows],
    )

    metric_ids = request.metrics or None
    metric_params = request.metric_params or None

    def _block(weights: dict[str, float]) -> ComparePortfolioBlock:
        report = compute_risk(
            symbols=universe.symbols,
            dates=universe.returns_dates,
            returns=universe.returns_matrix,
            benchmark_returns=benchmark_returns,
            weights=weights,
            risk_free_rate=settings.risk_free_rate,
            metric_ids=metric_ids,
            metric_params=metric_params,
        )
        return ComparePortfolioBlock(
            weights=dict(report.weights),
            metrics=dict(report.metrics),
            performance=_performance(report.performance),
        )

    try:
        current = (
            _block(request.current_weights) if request.current_weights else None
        )
        optimized = (
            _block(request.optimized_weights) if request.optimized_weights else None
        )
        equal_weights = {
            code: 1.0 / len(universe.symbols) for code in universe.symbols
        }
        equal_weight = _block(equal_weights)
        benchmark_report = compute_benchmark_risk(
            dates=universe.returns_dates,
            benchmark_returns=benchmark_returns,
            risk_free_rate=settings.risk_free_rate,
            metric_ids=metric_ids,
            metric_params=metric_params,
        )
    except KeyError as exc:
        identifier = exc.args[0] if exc.args else "?"
        raise HTTPException(status_code=422, detail=f"unknown id {identifier!r}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid parameters: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    known = set(universe.symbols)
    warnings = [f"{item.code} dropped: {item.reason}" for item in universe.dropped]
    for label, weights in (
        ("current", request.current_weights),
        ("optimized", request.optimized_weights),
    ):
        if not weights:
            continue
        ignored = sorted(code for code in weights if code.strip().upper() not in known)
        warnings.extend(
            f"weight ignored for {code}: not in the {label} universe"
            for code in ignored
        )

    return RiskCompareResponse(
        symbols=list(universe.symbols),
        dates=[day.isoformat() for day in universe.returns_dates],
        benchmark=benchmark,
        current=current,
        optimized=optimized,
        equal_weight=equal_weight,
        benchmark_portfolio=ComparePortfolioBlock(
            weights=dict(benchmark_report.weights),
            metrics=dict(benchmark_report.metrics),
            performance=_performance(benchmark_report.performance),
        ),
        options=_describe(risk_metrics),
        assumptions=assumptions_from(settings),
        warnings=warnings,
    )


@router.post("/risk/sharpe", response_model=SharpeResponse)
def compute_sharpe(request: SharpeRequest) -> SharpeResponse:
    """Compute the Sharpe ratio using the request's (or default) risk-free rate."""
    settings = request.settings or UserSettings()
    value = sharpe_ratio(request.mean_return, request.volatility, settings.risk_free_rate)
    return SharpeResponse(sharpe=value, assumptions=assumptions_from(settings))
