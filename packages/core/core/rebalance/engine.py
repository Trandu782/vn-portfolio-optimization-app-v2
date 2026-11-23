"""Rebalance engine: current holdings + target weights -> a placeable order list.

Pure orchestration. It never touches the network: the API supplies the latest
prices and the exchange per symbol. The brokerage fee is a user setting passed in
explicitly; the sell tax and lot sizes come from ``core.market_rules``.

Order-generation rules (stated in the UI as well):

* sells are planned before buys;
* a sell never exceeds the shares actually held;
* every order is rounded *down* to whole lots, so a full exit leaves any odd-lot
  remainder in the account;
* orders below ``min_notional`` are skipped;
* buys are funded from starting cash plus sell proceeds, so residual cash is
  never negative.

Target weights are fractions of the total portfolio value (holdings plus cash);
the remainder is target cash.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from core.optimize.engine import lot_size_for
from core.portfolio import Portfolio, portfolio_value_and_weights
from core.rebalance.interfaces import (
    DEFAULT_COST_MODEL,
    DEFAULT_MIN_NOTIONAL,
    DEFAULT_REBALANCE_POLICY,
    CostModel,
    OrderSide,
    PositionComparison,
    RebalanceContext,
    RebalanceOrder,
    RebalanceResult,
    build_cost_model,
    build_rebalance_policy,
)

#: Tolerance for floating-point drift when validating weight sums.
_WEIGHT_TOLERANCE = 1e-6
#: Sub-dong tolerance so an exact share count does not floor one share short.
_SHARE_EPSILON = 1e-6


@dataclass(frozen=True)
class _Candidate:
    """A symbol's current position, effective target and a few trading inputs."""

    symbol: str
    current_shares: int
    current_value: float
    current_weight: float
    target_weight: float
    target_value: float
    delta_value: float
    price: float | None
    lot_size: int


@dataclass(frozen=True)
class _OrderPlan:
    """A whole-lot order before costs and the minimum-notional check."""

    symbol: str
    side: OrderSide
    lots: int
    shares: int
    price: float
    lot_size: int


def rebalance(
    *,
    portfolio: Portfolio,
    prices: Mapping[str, float],
    target_weights: Mapping[str, float],
    exchanges: Mapping[str, str],
    brokerage_fee_rate: Decimal,
    cost_model: str = DEFAULT_COST_MODEL,
    policy: str = DEFAULT_REBALANCE_POLICY,
    policy_params: Mapping[str, Any] | None = None,
    min_notional: int = DEFAULT_MIN_NOTIONAL,
    market_rules: MarketRules = DEFAULT_MARKET_RULES,
) -> RebalanceResult:
    """Plan a rebalance from a portfolio and target weights.

    Args:
        portfolio: Current holdings and cash (validated by ``core.portfolio``).
        prices: Latest close per symbol, in VND. A missing price skips that
            symbol's order and adds a warning.
        target_weights: Desired weight per symbol as a fraction of total value.
        exchanges: Exchange code per symbol, used to pick the lot size.
        brokerage_fee_rate: The user's per-side fee as a fraction (a user setting).
        cost_model: Registered cost model id.
        policy: Registered rebalance policy id.
        policy_params: Parameters for the selected policy.
        min_notional: Skip any order whose value is below this many VND.
        market_rules: Market rules supplying the sell tax and lot sizes.

    Raises:
        ValueError: When the portfolio has no value, a weight is out of range, the
            weights sum to more than one, or ``min_notional`` is negative.
        KeyError: When a selected cost model or policy id is unknown.
        pydantic.ValidationError: When ``policy_params`` does not match the schema.
    """
    if min_notional < 0:
        raise ValueError("min_notional must not be negative")
    targets = _normalize_targets(target_weights)

    valuation = portfolio_value_and_weights(portfolio, prices)
    if valuation.total_value <= 0.0:
        raise ValueError("portfolio has no value to rebalance")

    decision = build_rebalance_policy(policy, _params(policy_params)).decide(
        RebalanceContext(
            current_weights=dict(valuation.weights),
            cash_weight=valuation.cash_weight,
            target_weights=targets,
            total_value=valuation.total_value,
        )
    )
    effective = dict(decision.effective_targets)

    model = build_cost_model(
        cost_model,
        brokerage_fee_rate=brokerage_fee_rate,
        sell_tax=market_rules.sell_tax,
    )
    held = {holding.symbol: holding.shares for holding in portfolio.holdings}
    candidates = [
        _candidate(
            symbol=symbol,
            total_value=valuation.total_value,
            held=held,
            current_value=valuation.market_values.get(symbol, 0.0),
            current_weight=valuation.weights.get(symbol, 0.0),
            target_weight=effective.get(symbol, 0.0),
            prices=prices,
            exchanges=exchanges,
            market_rules=market_rules,
        )
        for symbol in _ordered_symbols(portfolio, targets, effective)
    ]

    warnings: list[str] = []
    orders: list[RebalanceOrder] = []
    available_cash = float(portfolio.cash)

    # Sells first, so their proceeds fund the buys below.
    for candidate in candidates:
        if candidate.delta_value >= 0.0:
            continue
        plan = _plan_sell(candidate)
        if plan is None:
            if candidate.price is None and candidate.current_shares > 0:
                warnings.append(f"missing price for {candidate.symbol}; sell order skipped")
            continue
        value = _whole_vnd(plan.shares * plan.price)
        if value < min_notional:
            warnings.append(
                f"skipped sell {candidate.symbol}: value {value} is below the minimum "
                f"notional {min_notional}"
            )
            continue
        cost = model.estimate(value, "sell")
        orders.append(_order_from_plan(plan, value, cost.fee, cost.tax))
        available_cash += value - cost.total

    # Buys, funded greedily from the cash available after the sells.
    for candidate in candidates:
        if candidate.delta_value <= 0.0:
            continue
        plan = _plan_buy(candidate)
        if plan is None:
            if candidate.price is None:
                warnings.append(f"missing price for {candidate.symbol}; buy order skipped")
            continue
        order, available_cash, reason = _funded_buy(plan, model, min_notional, available_cash)
        if order is None:
            if reason is not None:
                warnings.append(reason)
        else:
            orders.append(order)

    total_fee = sum(order.fee for order in orders)
    total_tax = sum(order.tax for order in orders)
    return RebalanceResult(
        total_value=valuation.total_value,
        initial_cash=portfolio.cash,
        cash_weight=valuation.cash_weight,
        target_cash_weight=max(0.0, 1.0 - sum(effective.values())),
        positions=tuple(_position(candidate) for candidate in candidates),
        orders=tuple(orders),
        total_fee=total_fee,
        total_tax=total_tax,
        total_cost=total_fee + total_tax,
        turnover=sum(order.value for order in orders),
        residual_cash=max(0, round(available_cash)),
        cost_model=cost_model,
        policy=policy,
        policy_params=dict(policy_params or {}),
        lot_sizes={candidate.symbol: candidate.lot_size for candidate in candidates},
        brokerage_fee_rate=brokerage_fee_rate,
        sell_tax=market_rules.sell_tax,
        min_notional=min_notional,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _candidate(
    *,
    symbol: str,
    total_value: float,
    held: Mapping[str, int],
    current_value: float,
    current_weight: float,
    target_weight: float,
    prices: Mapping[str, float],
    exchanges: Mapping[str, str],
    market_rules: MarketRules,
) -> _Candidate:
    """Build a candidate from the valuation, the effective target and the price."""
    target_value = max(0.0, target_weight) * total_value
    return _Candidate(
        symbol=symbol,
        current_shares=held.get(symbol, 0),
        current_value=current_value,
        current_weight=current_weight,
        target_weight=target_weight,
        target_value=target_value,
        delta_value=target_value - current_value,
        price=_price(prices, symbol),
        lot_size=lot_size_for(exchanges.get(symbol, "HOSE"), market_rules),
    )


def _ordered_symbols(
    portfolio: Portfolio,
    targets: Mapping[str, float],
    effective: Mapping[str, float],
) -> list[str]:
    """Return holdings first (portfolio order), then any new target symbols."""
    ordered: list[str] = []
    seen: set[str] = set()
    for symbol in (
        [holding.symbol for holding in portfolio.holdings]
        + list(targets)
        + list(effective)
    ):
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return ordered


def _normalize_targets(target_weights: Mapping[str, float]) -> dict[str, float]:
    """Normalise symbols, reject bad weights and enforce a sum of at most one."""
    normalized: dict[str, float] = {}
    for raw_symbol, raw_weight in target_weights.items():
        symbol = raw_symbol.strip().upper()
        if not symbol:
            raise ValueError("target weight symbol must not be empty")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(f"target weight for {symbol} must be a non-negative number")
        if weight > 1.0 + _WEIGHT_TOLERANCE:
            raise ValueError(f"target weight for {symbol} must not exceed 1.0")
        normalized[symbol] = normalized.get(symbol, 0.0) + weight
    total = sum(normalized.values())
    if total > 1.0 + _WEIGHT_TOLERANCE:
        raise ValueError(f"target weights sum to {total:.4f}; they must not exceed 1.0")
    return normalized


def _price(prices: Mapping[str, float], symbol: str) -> float | None:
    """Return a usable positive price, or ``None`` when it is missing."""
    price = prices.get(symbol)
    if price is None or not math.isfinite(price) or price <= 0.0:
        return None
    return float(price)


def _plan_sell(candidate: _Candidate) -> _OrderPlan | None:
    """Plan a whole-lot sell, capped at the shares actually held."""
    if candidate.price is None or candidate.lot_size <= 0:
        return None
    wanted = math.floor((abs(candidate.delta_value) + _SHARE_EPSILON) / candidate.price)
    shares = min(wanted, candidate.current_shares)
    lots = shares // candidate.lot_size
    if lots <= 0:
        return None
    return _OrderPlan(
        symbol=candidate.symbol,
        side="sell",
        lots=lots,
        shares=lots * candidate.lot_size,
        price=candidate.price,
        lot_size=candidate.lot_size,
    )


def _plan_buy(candidate: _Candidate) -> _OrderPlan | None:
    """Plan a whole-lot buy for the full target delta."""
    if candidate.price is None or candidate.lot_size <= 0:
        return None
    wanted = math.floor((candidate.delta_value + _SHARE_EPSILON) / candidate.price)
    lots = wanted // candidate.lot_size
    if lots <= 0:
        return None
    return _OrderPlan(
        symbol=candidate.symbol,
        side="buy",
        lots=lots,
        shares=lots * candidate.lot_size,
        price=candidate.price,
        lot_size=candidate.lot_size,
    )


def _funded_buy(
    plan: _OrderPlan,
    model: CostModel,
    min_notional: int,
    available_cash: float,
) -> tuple[RebalanceOrder | None, float, str | None]:
    """Shrink a buy to the lots that fit the available cash, or skip it."""
    full_value = _whole_vnd(plan.shares * plan.price)
    if full_value < min_notional:
        return (
            None,
            available_cash,
            f"skipped buy {plan.symbol}: value {full_value} is below the minimum "
            f"notional {min_notional}",
        )
    per_lot = plan.price * float(plan.lot_size)
    affordable = int(available_cash // per_lot) if per_lot > 0.0 else 0
    lots = min(plan.lots, affordable)
    while lots > 0:
        shares = lots * plan.lot_size
        value = _whole_vnd(shares * plan.price)
        if value < min_notional:
            break
        cost = model.estimate(value, "buy")
        needed = value + cost.total
        if needed <= available_cash + 1e-9:
            order = RebalanceOrder(
                symbol=plan.symbol,
                side="buy",
                lots=lots,
                shares=shares,
                reference_price=plan.price,
                value=value,
                fee=cost.fee,
                tax=cost.tax,
            )
            return order, available_cash - needed, None
        lots -= 1
    return (
        None,
        available_cash,
        f"skipped buy {plan.symbol}: not enough cash after sells to fund a minimum order",
    )


def _order_from_plan(plan: _OrderPlan, value: int, fee: int, tax: int) -> RebalanceOrder:
    """Build a sell order from a plan (buys go through :func:`_funded_buy`)."""
    return RebalanceOrder(
        symbol=plan.symbol,
        side=plan.side,
        lots=plan.lots,
        shares=plan.shares,
        reference_price=plan.price,
        value=value,
        fee=fee,
        tax=tax,
    )


def _whole_vnd(value: float) -> int:
    """Round a notional to whole VND."""
    return round(value)


def _position(candidate: _Candidate) -> PositionComparison:
    """Map a candidate onto the current-versus-target comparison row."""
    return PositionComparison(
        symbol=candidate.symbol,
        current_shares=candidate.current_shares,
        current_value=candidate.current_value,
        current_weight=candidate.current_weight,
        target_weight=candidate.target_weight,
        target_value=candidate.target_value,
        delta_value=candidate.delta_value,
    )


def _params(policy_params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return policy parameters as a plain dict (or ``None`` when empty)."""
    return dict(policy_params) if policy_params else None


__all__ = ["rebalance"]
