"""Interfaces, registries and result types for the rebalance engine.

Every variable concept is an interface plus a registry, mirroring
``core.optimize`` and ``core.risk``:

* :class:`CostModel` -> :data:`cost_models`
* :class:`RebalancePolicy` -> :data:`rebalance_policies`

Adding an implementation is one new module with one ``@registry.register`` call;
the engine never switches on a concrete id. The brokerage fee is a user setting
and the sell tax and lot sizes live in ``core.market_rules``; those values travel
as explicit parameters and are never read from a constant here.

Weights are fractions of the *total* portfolio value (holdings plus cash), so the
remainder ``1 - sum(target_weights)`` is the target cash weight.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, cast

from core.registry import Registry

#: One order side: ``"buy"`` adds shares, ``"sell"`` removes them.
type OrderSide = Literal["buy", "sell"]

#: Product defaults (choices, not market data).
DEFAULT_COST_MODEL = "vn"
DEFAULT_REBALANCE_POLICY = "full"
DEFAULT_MIN_NOTIONAL = 1_000_000


@dataclass(frozen=True)
class OrderCost:
    """Estimated brokerage fee and sell tax for one order, in whole VND."""

    fee: int
    tax: int

    @property
    def total(self) -> int:
        """Return the total cost (fee plus tax) in whole VND."""
        return self.fee + self.tax


class CostModel(Protocol):
    """Estimate the brokerage fee and sell tax for a single order."""

    id: str

    def estimate(self, value: int, side: OrderSide) -> OrderCost:
        """Return the fee and tax for an order of ``value`` VND on ``side``."""


@dataclass(frozen=True)
class RebalanceContext:
    """Immutable inputs shared by every rebalance policy.

    Attributes:
        current_weights: Weight per held symbol as a fraction of total value.
        cash_weight: Current cash as a fraction of total value.
        target_weights: Requested target weight per symbol (fraction of total value).
        total_value: Total portfolio value in VND, including cash.
    """

    current_weights: Mapping[str, float]
    cash_weight: float
    target_weights: Mapping[str, float]
    total_value: float


@dataclass(frozen=True)
class RebalanceDecision:
    """The effective targets a policy wants the engine to trade toward."""

    effective_targets: Mapping[str, float]
    """Target weight per symbol as a fraction of total value (cash is the remainder)."""


class RebalancePolicy(Protocol):
    """Turn requested target weights into the weights actually traded toward."""

    id: str

    def decide(self, context: RebalanceContext) -> RebalanceDecision:
        """Return the effective target weights for ``context``."""


@dataclass(frozen=True)
class PositionComparison:
    """One symbol's current position next to its target."""

    symbol: str
    current_shares: int
    current_value: float
    current_weight: float
    target_weight: float
    target_value: float
    delta_value: float


@dataclass(frozen=True)
class RebalanceOrder:
    """One broker order: symbol, side, whole lots/shares, price and estimated costs."""

    symbol: str
    side: OrderSide
    lots: int
    shares: int
    reference_price: float
    value: int
    fee: int
    tax: int

    @property
    def total_cost(self) -> int:
        """Return the order's total estimated cost (fee plus tax)."""
        return self.fee + self.tax


@dataclass(frozen=True)
class RebalanceResult:
    """A complete rebalance: positions, a placeable order list and cost totals."""

    total_value: float
    initial_cash: int
    cash_weight: float
    target_cash_weight: float
    positions: tuple[PositionComparison, ...]
    orders: tuple[RebalanceOrder, ...]
    total_fee: int
    total_tax: int
    total_cost: int
    turnover: int
    residual_cash: int
    cost_model: str
    policy: str
    policy_params: Mapping[str, Any]
    lot_sizes: Mapping[str, int]
    brokerage_fee_rate: Decimal
    sell_tax: Decimal
    min_notional: int
    warnings: tuple[str, ...]


# -- registries --------------------------------------------------------------

#: Registry of every available trading cost model.
cost_models: Registry[CostModel] = Registry()

#: Registry of every available rebalance policy.
rebalance_policies: Registry[RebalancePolicy] = Registry()


class _CostModelFactory(Protocol):
    """Constructor shape shared by every cost model."""

    def __call__(
        self, *, brokerage_fee_rate: Decimal, sell_tax: Decimal
    ) -> CostModel: ...


class _PolicyFactory(Protocol):
    """Constructor shape shared by every rebalance policy."""

    def __call__(self, params: dict[str, Any] | None = None) -> RebalancePolicy: ...


def build_cost_model(
    identifier: str,
    *,
    brokerage_fee_rate: Decimal,
    sell_tax: Decimal,
    registry: Registry[CostModel] | None = None,
) -> CostModel:
    """Instantiate the cost model registered under ``identifier``.

    The brokerage fee (a user setting) and the sell tax (from ``market_rules``)
    are passed explicitly so no implementation reads them from a global.

    Raises:
        KeyError: If ``identifier`` is unknown.
    """
    factory = cast("_CostModelFactory", (registry or cost_models).get(identifier))
    return factory(brokerage_fee_rate=brokerage_fee_rate, sell_tax=sell_tax)


def build_rebalance_policy(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[RebalancePolicy] | None = None,
) -> RebalancePolicy:
    """Instantiate the rebalance policy registered under ``identifier``.

    Raises:
        KeyError: If ``identifier`` is unknown.
        pydantic.ValidationError: If ``params`` does not match the policy schema.
    """
    factory = cast("_PolicyFactory", (registry or rebalance_policies).get(identifier))
    return factory(params)


__all__ = [
    "DEFAULT_COST_MODEL",
    "DEFAULT_MIN_NOTIONAL",
    "DEFAULT_REBALANCE_POLICY",
    "CostModel",
    "OrderCost",
    "OrderSide",
    "PositionComparison",
    "RebalanceContext",
    "RebalanceDecision",
    "RebalanceOrder",
    "RebalancePolicy",
    "RebalanceResult",
    "build_cost_model",
    "build_rebalance_policy",
    "cost_models",
    "rebalance_policies",
]
