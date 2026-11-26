"""Rebalance routes: the option catalogue, a full rebalance and a cost helper.

``POST /rebalance`` values the current holdings at the latest close, applies the
selected policy to the requested target weights and returns a placeable order list
with estimated fees and tax, the turnover and the residual cash. ``GET
/rebalance/options`` publishes the cost-model and policy catalogues so the UI
renders them without hardcoding. ``POST /rebalance/cost`` is the small fee helper.

The routes are thin: structure validation lives in ``core.portfolio`` and the order
planning in ``core.rebalance``. A missing price skips that symbol's order and is
reported as a warning, mirroring ``/portfolio/evaluate``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from app.api.v1.data import get_data_service
from app.api.v1.schemas import Assumptions, assumptions_from
from core.costs import commission, round_trip_commission
from core.portfolio import Holding, Portfolio
from core.rebalance import (
    DEFAULT_COST_MODEL,
    DEFAULT_MIN_NOTIONAL,
    DEFAULT_REBALANCE_POLICY,
    RebalanceResult,
    cost_models,
    rebalance_policies,
)
from core.rebalance import rebalance as run_rebalance_engine
from core.registry import Registry
from core.settings import UserSettings
from core.universe import normalize_exchange
from data.service import DataService

router = APIRouter(tags=["rebalance"])


class CostRequest(BaseModel):
    """Inputs for the rebalance cost estimate. Settings default when omitted."""

    notional: int = Field(
        ..., ge=0, description="Traded value in VND (for example, 100000000)."
    )
    settings: UserSettings | None = Field(
        default=None,
        description="User settings. Defaults apply when omitted.",
    )


class CostResponse(BaseModel):
    """Estimated commission and the settings used to compute it."""

    commission: int
    round_trip_commission: int
    assumptions: Assumptions


@router.post("/rebalance/cost", response_model=CostResponse)
def estimate_cost(request: CostRequest) -> CostResponse:
    """Estimate the brokerage commission using the request's (or default) fee."""
    settings = request.settings or UserSettings()
    return CostResponse(
        commission=commission(request.notional, settings.brokerage_fee_rate),
        round_trip_commission=round_trip_commission(
            request.notional, settings.brokerage_fee_rate
        ),
        assumptions=assumptions_from(settings),
    )


# -- option catalogue --------------------------------------------------------


class OptionResponse(BaseModel):
    """Registry metadata for one cost model or rebalance policy."""

    id: str
    name: str
    description: str
    parameter_schema: dict[str, Any] | None


class RebalanceDefaults(BaseModel):
    """Defaults the UI should preselect."""

    cost_model: str
    policy: str
    min_notional: int


class RebalanceOptionsResponse(BaseModel):
    """Cost models and policies, published for the UI to render."""

    cost_models: list[OptionResponse]
    policies: list[OptionResponse]
    defaults: RebalanceDefaults


def _describe[T](registry: Registry[T]) -> list[OptionResponse]:
    """Map a registry's metadata onto the API option response."""
    return [
        OptionResponse(
            id=info.id,
            name=info.name,
            description=info.description,
            parameter_schema=info.parameter_schema,
        )
        for info in registry.describe()
    ]


@router.get("/rebalance/options", response_model=RebalanceOptionsResponse)
def rebalance_options(response: Response) -> RebalanceOptionsResponse:
    """Return the cost-model and policy catalogues and the defaults."""
    response.headers["Cache-Control"] = (
        "public, max-age=300, s-maxage=3600, stale-while-revalidate=7200"
    )
    return RebalanceOptionsResponse(
        cost_models=_describe(cost_models),
        policies=_describe(rebalance_policies),
        defaults=RebalanceDefaults(
            cost_model=DEFAULT_COST_MODEL,
            policy=DEFAULT_REBALANCE_POLICY,
            min_notional=DEFAULT_MIN_NOTIONAL,
        ),
    )


# -- a full rebalance --------------------------------------------------------


class RebalanceRequest(BaseModel):
    """Inputs for one rebalance. Settings default when omitted."""

    holdings: list[Holding] = Field(default_factory=list, description="Current holdings.")
    cash: int = Field(default=0, ge=0, description="Cash balance in whole VND.")
    target_weights: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Target weight per symbol as a fraction of total value "
            "(the remainder is target cash)."
        ),
    )
    cost_model: str = Field(default=DEFAULT_COST_MODEL, description="Cost model id.")
    policy: str = Field(default=DEFAULT_REBALANCE_POLICY, description="Rebalance policy id.")
    policy_params: dict[str, Any] = Field(default_factory=dict)
    min_notional: int = Field(
        default=DEFAULT_MIN_NOTIONAL,
        ge=0,
        description="Skip orders whose value is below this many VND.",
    )
    settings: UserSettings | None = Field(
        default=None,
        description="User settings. Defaults apply when omitted.",
    )


class RebalancePositionResponse(BaseModel):
    """One symbol's current position next to its target."""

    symbol: str
    current_shares: int
    current_value: float
    current_weight: float
    target_weight: float
    target_value: float
    delta_value: float


class RebalanceOrderResponse(BaseModel):
    """One placeable order with its estimated fee and tax."""

    symbol: str
    side: str
    lots: int
    shares: int
    reference_price: float
    value: int
    fee: int
    tax: int


class RebalanceAssumptions(BaseModel):
    """The settings, market rules and data provenance used to plan the orders."""

    brokerage_fee_rate: float
    sell_tax: float
    min_notional: int
    cost_model: str
    policy: str
    data_sources: list[str]
    latest_date: date | None
    prices_adjusted: bool
    lot_sizes: dict[str, int]


class RebalanceResponse(BaseModel):
    """The order list, current-versus-target positions and the cost summary."""

    total_value: float
    initial_cash: int
    cash_weight: float
    target_cash_weight: float
    positions: list[RebalancePositionResponse]
    orders: list[RebalanceOrderResponse]
    total_fee: int
    total_tax: int
    total_cost: int
    turnover: int
    residual_cash: int
    cost_model: str
    policy: str
    policy_params: dict[str, Any]
    assumptions: RebalanceAssumptions
    warnings: list[str]


@router.post("/rebalance", response_model=RebalanceResponse)
def run_rebalance(
    request: RebalanceRequest,
    service: Annotated[DataService, Depends(get_data_service)],
) -> RebalanceResponse:
    """Plan a rebalance and return a placeable order list."""
    try:
        portfolio = Portfolio(holdings=request.holdings, cash=request.cash)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    targets = _normalize_targets(request.target_weights)
    symbols = _symbols(portfolio, targets)
    if not symbols:
        raise HTTPException(
            status_code=422, detail="provide at least one holding or target weight"
        )

    prices, exchanges, sources, latest_date, warnings = _market_data(service, symbols)
    settings = request.settings or UserSettings()
    try:
        result = run_rebalance_engine(
            portfolio=portfolio,
            prices=prices,
            target_weights=targets,
            exchanges=exchanges,
            brokerage_fee_rate=settings.brokerage_fee_rate,
            cost_model=request.cost_model,
            policy=request.policy,
            policy_params=request.policy_params,
            min_notional=request.min_notional,
        )
    except KeyError as exc:
        identifier = exc.args[0] if exc.args else "?"
        raise HTTPException(status_code=422, detail=f"unknown id {identifier!r}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid parameters: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _to_response(result, sources, latest_date, warnings)


def _normalize_targets(target_weights: dict[str, float]) -> dict[str, float]:
    """Upper-case symbols and sum any duplicates; reject an empty code."""
    targets: dict[str, float] = {}
    for raw_symbol, weight in target_weights.items():
        code = raw_symbol.strip().upper()
        if not code:
            raise HTTPException(
                status_code=422, detail="target weight symbol must not be empty"
            )
        targets[code] = targets.get(code, 0.0) + float(weight)
    return targets


def _symbols(portfolio: Portfolio, targets: dict[str, float]) -> list[str]:
    """Return holdings first, then any new target symbols, without duplicates."""
    ordered: list[str] = []
    seen: set[str] = set()
    for symbol in portfolio.symbols + list(targets):
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return ordered


def _market_data(
    service: DataService, symbols: list[str]
) -> tuple[dict[str, float], dict[str, str], list[str], date | None, list[str]]:
    """Load latest closes and exchanges (backfilling on demand) for ``symbols``."""
    prices: dict[str, float] = {}
    exchanges: dict[str, str] = {}
    warnings: list[str] = []
    sources: set[str] = set()
    latest_date: date | None = None
    series_by_symbol = service.get_prices_preferring_v2_spot_batch(
        symbols, recent_days=45
    )
    for symbol in symbols:
        series = series_by_symbol[symbol.upper()]
        warnings.extend(series.warnings)
        if series.source:
            sources.add(series.source)
        if series.rows:
            latest = series.rows[-1]
            prices[symbol] = float(latest.close)
            if latest_date is None or latest.date > latest_date:
                latest_date = latest.date
        info = service.get_symbol(symbol)
        exchanges[symbol] = (
            normalize_exchange(info.exchange) if info and info.exchange else "HOSE"
        )
    return prices, exchanges, sorted(sources), latest_date, warnings


def _to_response(
    result: RebalanceResult,
    sources: list[str],
    latest_date: date | None,
    extra_warnings: Iterable[str],
) -> RebalanceResponse:
    """Map the core result onto the API response model."""
    return RebalanceResponse(
        total_value=result.total_value,
        initial_cash=result.initial_cash,
        cash_weight=result.cash_weight,
        target_cash_weight=result.target_cash_weight,
        positions=[
            RebalancePositionResponse(
                symbol=item.symbol,
                current_shares=item.current_shares,
                current_value=item.current_value,
                current_weight=item.current_weight,
                target_weight=item.target_weight,
                target_value=item.target_value,
                delta_value=item.delta_value,
            )
            for item in result.positions
        ],
        orders=[
            RebalanceOrderResponse(
                symbol=item.symbol,
                side=item.side,
                lots=item.lots,
                shares=item.shares,
                reference_price=item.reference_price,
                value=item.value,
                fee=item.fee,
                tax=item.tax,
            )
            for item in result.orders
        ],
        total_fee=result.total_fee,
        total_tax=result.total_tax,
        total_cost=result.total_cost,
        turnover=result.turnover,
        residual_cash=result.residual_cash,
        cost_model=result.cost_model,
        policy=result.policy,
        policy_params=dict(result.policy_params),
        assumptions=RebalanceAssumptions(
            brokerage_fee_rate=float(result.brokerage_fee_rate),
            sell_tax=float(result.sell_tax),
            min_notional=result.min_notional,
            cost_model=result.cost_model,
            policy=result.policy,
            data_sources=sources,
            latest_date=latest_date,
            prices_adjusted=False,
            lot_sizes=dict(result.lot_sizes),
        ),
        warnings=list(dict.fromkeys([*extra_warnings, *result.warnings])),
    )
