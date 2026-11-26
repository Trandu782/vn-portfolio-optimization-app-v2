"""Optimization routes: the option catalogue and a full optimization.

The routes are thin. They resolve the requested symbols through the data service
(backfilling on demand), reuse ``core.universe.build_universe`` to assemble the
aligned returns matrix and latest prices, then call ``core.optimize.optimize``.
Every option list is published from a core registry so the UI renders it without
hardcoding. Expected returns and covariance always use the sample estimators.

Errors map to 422 with a clear message: an unknown or invalid id, structurally
invalid input, or constraints the solver cannot satisfy.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from app.api.v1.data import get_data_service
from app.api.v1.universe import _load_symbol_series_batch, _stale_warnings
from core.market_rules import DEFAULT_MARKET_RULES
from core.optimize import (
    DEFAULT_COVARIANCE_ESTIMATOR,
    DEFAULT_FRONTIER_POINTS,
    DEFAULT_MAX_WEIGHT,
    DEFAULT_OBJECTIVE,
    DEFAULT_RANDOM_PORTFOLIOS,
    DEFAULT_RETURN_ESTIMATOR,
    DEFAULT_SOLVER,
    DEFAULT_TRADING_DAYS,
    ConstraintSpec,
    FrontierResult,
    InfeasibleConstraintsError,
    OptimizeResult,
    PortfolioPoint,
    build_efficient_frontier,
    constraints,
    lot_size_for,
    objectives,
    optimize,
    resolve_risk_free_rate,
    risk_free_rate_providers,
    round_to_lots,
    solvers,
    stratified_cloud_indices,
    universe_size_warnings,
)
from core.registry import Registry
from core.settings import Settings, UserSettings
from core.universe import UniverseBuildResult, build_universe
from data.service import DataService

router = APIRouter(tags=["optimize"])


class OptionResponse(BaseModel):
    """Registry metadata for one optimizer option."""

    id: str
    name: str
    description: str
    parameter_schema: dict[str, Any] | None


class OptimizeDefaults(BaseModel):
    """The conservative defaults the UI should preselect."""

    objective: str
    solver: str
    max_weight: float


class FrontierDefaults(BaseModel):
    """Defaults and limits for the efficient-frontier view."""

    portfolios: int
    max_portfolios: int
    cloud_points: int = Field(
        ...,
        description=(
            "Scatter points a frontier response plots. The simulation runs every "
            "requested portfolio and the response carries a stratified sample of "
            "at most this many."
        ),
    )
    frontier_points: int
    seed: int | None = None
    max_stocks: int


class OptimizeOptionsResponse(BaseModel):
    """Every optimizer concept, published for the UI to render."""

    objectives: list[OptionResponse]
    constraints: list[OptionResponse]
    solvers: list[OptionResponse]
    risk_free_rate_providers: list[OptionResponse]
    defaults: OptimizeDefaults
    frontier_defaults: FrontierDefaults


class ConstraintSelection(BaseModel):
    """One constraint to apply, with its parameters."""

    id: str = Field(..., description="Constraint id from /optimize/options.")
    params: dict[str, Any] = Field(default_factory=dict)


def _default_constraints() -> list[ConstraintSelection]:
    """Return the conservative default: a 25% maximum weight per position."""
    return [
        ConstraintSelection(id="max_weight", params={"max_weight": DEFAULT_MAX_WEIGHT})
    ]


class OptimizeRequest(BaseModel):
    """Inputs for one optimization run. Settings default when omitted."""

    symbols: list[str] = Field(default_factory=list, description="Ticker codes to optimize.")
    start: date
    end: date
    capital: int = Field(..., ge=0, description="Capital to invest in VND.")
    objective: str = Field(default=DEFAULT_OBJECTIVE, description="Objective id.")
    constraints: list[ConstraintSelection] = Field(default_factory=_default_constraints)
    risk_free_rate_provider: str = Field(
        default="user_settings",
        description="Risk-free-rate provider id (user settings today).",
    )
    settings: UserSettings | None = Field(
        default=None,
        description="User settings. Defaults apply when omitted.",
    )
    sectors: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional ticker -> sector map for the maximum-sector-weight constraint. "
            "Symbols missing from the map are grouped as 'Unknown'."
        ),
    )


class AssumptionsResponse(BaseModel):
    """Every setting used to produce the result, for reproducibility."""

    objective: str
    return_estimator: dict[str, Any]
    covariance_estimator: dict[str, Any]
    constraints: list[dict[str, Any]]
    capital: int
    investable_capital: int
    cash_reserve: float
    risk_free_rate: float
    risk_free_rate_provider: str
    start: date
    end: date
    data_sources: list[str]
    prices_adjusted: bool
    lot_sizes: dict[str, int]


class OptimizeResponse(BaseModel):
    """Weights, integer lots, statistics and assumptions for one optimization."""

    symbols: list[str]
    weights: dict[str, float]
    lots: dict[str, int]
    shares: dict[str, int]
    values: dict[str, float]
    residual_cash: int
    cash_reserve: float
    cash_reserve_value: int
    total_cash: int
    expected_return: float
    volatility: float
    sharpe: float
    solver_status: str
    solver_message: str
    binding_constraints: list[str]
    assumptions: AssumptionsResponse
    warnings: list[str] = Field(default_factory=list)


class FrontierRequest(BaseModel):
    """Inputs for one efficient-frontier run. Settings default when omitted."""

    symbols: list[str] = Field(default_factory=list, description="Ticker codes to optimize.")
    start: date
    end: date
    capital: int = Field(..., ge=0, description="Capital to invest in VND (for lots and cash).")
    max_weight: float = Field(
        default=DEFAULT_MAX_WEIGHT,
        gt=0.0,
        le=1.0,
        description="Maximum weight per stock as a fraction (0.25 == 25%).",
    )
    num_portfolios: int = Field(
        default=DEFAULT_RANDOM_PORTFOLIOS,
        ge=1,
        description=(
            "Number of random portfolios drawn for the cloud. The statistics use "
            "all of them; the response plots a stratified sample (see "
            "frontier_defaults.cloud_points)."
        ),
    )
    seed: int | None = Field(default=None, description="Seed for the random cloud.")
    current_weights: dict[str, float] = Field(
        default_factory=dict,
        description="The user's current portfolio weights, plotted as a marker.",
    )
    risk_free_rate_provider: str = Field(
        default="user_settings",
        description="Risk-free-rate provider id (user settings today).",
    )
    settings: UserSettings | None = Field(
        default=None,
        description="User settings. Defaults apply when omitted.",
    )
    sectors: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional ticker -> sector map for the maximum-sector-weight constraint. "
            "Symbols missing from the map are grouped as 'Unknown'."
        ),
    )
    max_sector_weight: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Optional maximum weight per sector as a fraction (0.30 == 30%). Applied "
            "to the exact frontier and the random cloud."
        ),
    )


class RandomCloudPointResponse(BaseModel):
    """One random portfolio plotted on the scatter (no weights)."""

    expected_return: float
    volatility: float
    sharpe: float


class FrontierPointResponse(BaseModel):
    """A marked or swept portfolio with weights, statistics and integer lots."""

    weights: dict[str, float]
    expected_return: float
    volatility: float
    sharpe: float
    lots: dict[str, int]
    shares: dict[str, int]
    values: dict[str, float]
    residual_cash: int


class FrontierAssumptionsResponse(BaseModel):
    """Every setting the frontier used, echoed for reproducibility."""

    data_sources: list[str]
    start: date
    end: date
    prices_adjusted: bool
    risk_free_rate: float
    return_estimator: str
    covariance_estimator: str
    seed: int | None
    max_weight: float
    portfolios_requested: int
    portfolios_generated: int
    portfolios_plotted: int = Field(
        ...,
        description=(
            "Random-cloud points in this response (a stratified sample of "
            "portfolios_generated)."
        ),
    )
    frontier_points: int
    skipped_targets: int
    trading_days: int
    lot_sizes: dict[str, int]
    max_sector_weight: float | None = None


class FrontierResponse(BaseModel):
    """The random cloud, the exact frontier, the marked portfolios and assumptions."""

    symbols: list[str]
    risk_free_rate: float
    random_cloud: list[RandomCloudPointResponse]
    frontier: list[FrontierPointResponse]
    min_variance: FrontierPointResponse
    tangency: FrontierPointResponse
    equal_weight: FrontierPointResponse
    current: FrontierPointResponse | None
    assumptions: FrontierAssumptionsResponse
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


@router.get("/optimize/options", response_model=OptimizeOptionsResponse)
def read_optimize_options(response: Response) -> OptimizeOptionsResponse:
    """Publish every optimizer concept and the conservative defaults."""
    response.headers["Cache-Control"] = (
        "public, max-age=300, s-maxage=3600, stale-while-revalidate=7200"
    )
    return OptimizeOptionsResponse(
        objectives=_describe(objectives),
        constraints=_describe(constraints),
        solvers=_describe(solvers),
        risk_free_rate_providers=_describe(risk_free_rate_providers),
        defaults=OptimizeDefaults(
            objective=DEFAULT_OBJECTIVE,
            solver=DEFAULT_SOLVER,
            max_weight=DEFAULT_MAX_WEIGHT,
        ),
        frontier_defaults=FrontierDefaults(
            portfolios=DEFAULT_RANDOM_PORTFOLIOS,
            max_portfolios=Settings().frontier_max_portfolios,
            cloud_points=Settings().frontier_cloud_points,
            frontier_points=DEFAULT_FRONTIER_POINTS,
            max_stocks=Settings().max_optimize_stocks,
        ),
    )


@router.post("/optimize", response_model=OptimizeResponse)
def run_optimize(
    request: OptimizeRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> OptimizeResponse:
    """Optimize the requested symbols and return weights, lots and assumptions."""
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    codes = _dedupe(request.symbols)
    config = Settings()
    if len(codes) > config.max_optimize_stocks:
        raise HTTPException(
            status_code=422,
            detail=(
                f"at most {config.max_optimize_stocks} stocks per optimization; "
                f"received {len(codes)}"
            ),
        )
    if not codes:
        raise HTTPException(status_code=422, detail="provide at least one symbol")
    sectors = _normalize_sectors(request.sectors, codes)

    series, sources_by_code = _load_symbol_series_batch(
        service, codes, request.start, request.end
    )
    universe = build_universe(series, [], request.start, request.end)
    if not universe.symbols:
        raise HTTPException(
            status_code=422,
            detail="no V2 price data available for the requested symbols",
        )
    exchanges = {item.code: item.exchange for item in series}
    settings = request.settings or UserSettings()
    data_sources = sorted(
        {sources_by_code[code] for code in universe.symbols if code in sources_by_code}
    )

    try:
        risk_free_rate = resolve_risk_free_rate(request.risk_free_rate_provider, settings)
        result = optimize(
            symbols=universe.symbols,
            exchanges=exchanges,
            returns=universe.returns_matrix,
            prices=_latest_prices(universe),
            capital=request.capital,
            objective_id=request.objective,
            return_estimator_id=DEFAULT_RETURN_ESTIMATOR,
            covariance_estimator_id=DEFAULT_COVARIANCE_ESTIMATOR,
            constraint_specs=[
                ConstraintSpec(item.id, item.params) for item in request.constraints
            ],
            risk_free_rate=risk_free_rate,
            start=request.start,
            end=request.end,
            risk_free_rate_provider=request.risk_free_rate_provider,
            data_sources=data_sources,
            prices_adjusted=False,
            sectors=sectors,
        )
    except KeyError as exc:
        identifier = exc.args[0] if exc.args else "?"
        raise HTTPException(status_code=422, detail=f"unknown id {identifier!r}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid parameters: {exc}") from exc
    except InfeasibleConstraintsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    warnings = [f"{item.code} dropped: {item.reason}" for item in universe.dropped]
    warnings.extend(_stale_warnings(universe))
    return _to_response(result, warnings)


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


#: Upper bound on the ticker -> sector map size (a safety limit, not a setting).
MAX_SECTOR_MAP_ENTRIES = 5_000


def _normalize_sectors(
    sectors: dict[str, str] | None, codes: list[str]
) -> dict[str, str] | None:
    """Upper-case the sector map, keep the requested symbols and cap its size.

    A symbol with no entry is grouped as ``Unknown`` by the core helper, so a
    partial map is valid. An oversized map (or a non-string entry that Pydantic
    did not already reject) is a 422.
    """
    if sectors is None:
        return None
    if len(sectors) > MAX_SECTOR_MAP_ENTRIES:
        raise HTTPException(
            status_code=422,
            detail=f"the sector map is limited to {MAX_SECTOR_MAP_ENTRIES} entries",
        )
    wanted = {code.strip().upper() for code in codes}
    normalized: dict[str, str] = {}
    for raw_code, raw_sector in sectors.items():
        if not isinstance(raw_code, str) or not isinstance(raw_sector, str):
            raise HTTPException(
                status_code=422,
                detail="the sector map must map tickers to sector names (strings)",
            )
        code = raw_code.strip().upper()
        if code in wanted:
            normalized[code] = raw_sector.strip()
    return normalized


def _latest_prices(universe: UniverseBuildResult) -> dict[str, float]:
    """Return the last finite close per symbol from the aligned price matrix."""
    prices: dict[str, float] = {}
    matrix = universe.price_matrix
    for index, code in enumerate(universe.symbols):
        column = matrix[:, index]
        finite = column[np.isfinite(column)]
        if finite.size:
            prices[code] = float(finite[-1])
    return prices


def _to_response(result: OptimizeResult, warnings: list[str]) -> OptimizeResponse:
    """Map the core result onto the API response model."""
    assumptions = result.assumptions
    return OptimizeResponse(
        symbols=list(result.symbols),
        weights=dict(result.weights),
        lots=dict(result.lots),
        shares=dict(result.shares),
        values=dict(result.values),
        residual_cash=result.residual_cash,
        cash_reserve=result.cash_reserve,
        cash_reserve_value=result.cash_reserve_value,
        total_cash=result.total_cash,
        expected_return=result.expected_return,
        volatility=result.volatility,
        sharpe=result.sharpe,
        solver_status=result.solver_status,
        solver_message=result.solver_message,
        binding_constraints=list(result.binding_constraints),
        assumptions=AssumptionsResponse(
            objective=assumptions.objective,
            return_estimator=dict(assumptions.return_estimator),
            covariance_estimator=dict(assumptions.covariance_estimator),
            constraints=[dict(item) for item in assumptions.constraints],
            capital=assumptions.capital,
            investable_capital=assumptions.investable_capital,
            cash_reserve=assumptions.cash_reserve,
            risk_free_rate=assumptions.risk_free_rate,
            risk_free_rate_provider=assumptions.risk_free_rate_provider,
            start=assumptions.start,
            end=assumptions.end,
            data_sources=list(assumptions.data_sources),
            prices_adjusted=assumptions.prices_adjusted,
            lot_sizes=dict(assumptions.lot_sizes),
        ),
        warnings=warnings,
    )


def _lot_sizes_for(symbols: tuple[str, ...], exchanges: dict[str, str]) -> dict[str, int]:
    """Return the integer lot size per symbol using the market rules."""
    return {
        code: lot_size_for(exchanges.get(code, "HOSE"), DEFAULT_MARKET_RULES)
        for code in symbols
    }


def _round_point(
    point: PortfolioPoint,
    prices: dict[str, float],
    lot_sizes: dict[str, int],
    capital: int,
) -> FrontierPointResponse:
    """Attach integer lots and residual cash to a frontier point."""
    rounding = round_to_lots(
        weights=dict(point.weights),
        prices=prices,
        capital=float(capital),
        lot_sizes=lot_sizes,
    )
    return FrontierPointResponse(
        weights=dict(point.weights),
        expected_return=point.expected_return,
        volatility=point.volatility,
        sharpe=point.sharpe,
        lots=dict(rounding.lots),
        shares=dict(rounding.shares),
        values=dict(rounding.values),
        residual_cash=rounding.residual_cash,
    )


@router.post("/optimize/frontier", response_model=FrontierResponse)
def run_frontier(
    request: FrontierRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> FrontierResponse:
    """Build the random cloud, the exact frontier and the marked portfolios."""
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    codes = _dedupe(request.symbols)
    config = Settings()
    if len(codes) > config.max_optimize_stocks:
        raise HTTPException(
            status_code=422,
            detail=(
                f"at most {config.max_optimize_stocks} stocks per optimization; "
                f"received {len(codes)}"
            ),
        )
    if not codes:
        raise HTTPException(status_code=422, detail="provide at least one symbol")
    sectors = _normalize_sectors(request.sectors, codes)

    series, sources_by_code = _load_symbol_series_batch(
        service, codes, request.start, request.end
    )
    universe = build_universe(series, [], request.start, request.end)
    if not universe.symbols:
        raise HTTPException(
            status_code=422, detail="no V2 price data available for the requested symbols"
        )
    exchanges = {item.code: item.exchange for item in series}
    settings = request.settings or UserSettings()
    data_sources = sorted(
        {sources_by_code[code] for code in universe.symbols if code in sources_by_code}
    )

    try:
        risk_free_rate = resolve_risk_free_rate(request.risk_free_rate_provider, settings)
        result = build_efficient_frontier(
            returns=universe.returns_matrix,
            symbols=universe.symbols,
            risk_free_rate=risk_free_rate,
            max_weight=request.max_weight,
            current_weights=request.current_weights or None,
            num_portfolios=request.num_portfolios,
            seed=request.seed,
            time_budget=config.frontier_time_budget,
            hard_max_portfolios=config.frontier_max_portfolios,
            trading_days=DEFAULT_TRADING_DAYS,
            sectors=sectors,
            max_sector_weight=request.max_sector_weight,
        )
    except KeyError as exc:
        identifier = exc.args[0] if exc.args else "?"
        raise HTTPException(status_code=422, detail=f"unknown id {identifier!r}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid parameters: {exc}") from exc
    except InfeasibleConstraintsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _frontier_to_response(
        result,
        universe,
        exchanges,
        data_sources,
        request.start,
        request.end,
        request.capital,
        config,
    )


def _frontier_to_response(
    result: FrontierResult,
    universe: UniverseBuildResult,
    exchanges: dict[str, str],
    data_sources: list[str],
    start: date,
    end: date,
    capital: int,
    config: Settings,
) -> FrontierResponse:
    """Map the core frontier result onto the API response, rounding every point.

    The cloud is plotted as a stratified sample of at most
    ``config.frontier_cloud_points`` points: the simulation itself always runs every
    requested portfolio, and the sample keeps the hull and the density of the cloud
    while keeping the payload small. The exact frontier and the marked portfolios
    are never sampled.
    """
    prices = _latest_prices(universe)
    lot_sizes = _lot_sizes_for(universe.symbols, exchanges)
    cloud = result.random_cloud
    plotted = stratified_cloud_indices(
        cloud.returns,
        cloud.volatilities,
        max_points=config.frontier_cloud_points,
    )
    cloud_points = [
        RandomCloudPointResponse(
            expected_return=float(cloud.returns[index]),
            volatility=float(cloud.volatilities[index]),
            sharpe=float(cloud.sharpes[index]),
        )
        for index in plotted
    ]
    assumptions = result.assumptions
    warnings = [f"{item.code} dropped: {item.reason}" for item in universe.dropped]
    warnings.extend(_stale_warnings(universe))
    warnings.extend(universe_size_warnings(len(universe.symbols)))
    warnings.append(
        "In-sample: these weights come from historical estimates over the selected "
        "window; they are decision support, not a forecast or financial advice."
    )
    current = (
        _round_point(result.current, prices, lot_sizes, capital)
        if result.current is not None
        else None
    )
    return FrontierResponse(
        symbols=list(result.symbols),
        risk_free_rate=float(assumptions.risk_free_rate),
        random_cloud=cloud_points,
        frontier=[_round_point(point, prices, lot_sizes, capital) for point in result.frontier],
        min_variance=_round_point(result.min_variance, prices, lot_sizes, capital),
        tangency=_round_point(result.tangency, prices, lot_sizes, capital),
        equal_weight=_round_point(result.equal_weight, prices, lot_sizes, capital),
        current=current,
        assumptions=FrontierAssumptionsResponse(
            data_sources=data_sources,
            start=start,
            end=end,
            prices_adjusted=False,
            risk_free_rate=float(assumptions.risk_free_rate),
            return_estimator="historical_mean",
            covariance_estimator="sample",
            seed=assumptions.seed,
            max_weight=float(assumptions.max_weight),
            portfolios_requested=assumptions.portfolios_requested,
            portfolios_generated=assumptions.portfolios_generated,
            portfolios_plotted=len(cloud_points),
            frontier_points=assumptions.frontier_points,
            skipped_targets=assumptions.skipped_targets,
            trading_days=assumptions.trading_days,
            lot_sizes=lot_sizes,
            max_sector_weight=assumptions.max_sector_weight,
        ),
        warnings=warnings,
    )
