# Extending the optimizer

Every variable concept is an **interface plus a registry**, never an `if/else` or
`switch` chain. Adding a feature means **one new file that implements the
interface plus one registration**. The API publishes `Registry.describe()`, so
the UI renders new options without a code change.

| Concept | Interface | Registry | Built-ins live in |
| --- | --- | --- | --- |
| Objective | `core.optimize.interfaces.Objective` | `core.optimize.interfaces.objectives` | `packages/core/core/optimize/objectives/` |
| Constraint | `core.optimize.interfaces.Constraint` | `constraints` | `packages/core/core/optimize/constraints/` |
| Return estimator | `core.optimize.interfaces.ReturnEstimator` | `return_estimators` | `packages/core/core/optimize/return_estimators/` |
| Covariance estimator | `core.optimize.interfaces.CovarianceEstimator` | `covariance_estimators` | `packages/core/core/optimize/covariance_estimators/` |
| Data provider | `data.interfaces.DataProvider` | `data.registry.data_providers` | `packages/data/data/providers/` |
| Risk metric | `core.risk.interfaces.RiskMetric` | `core.risk.interfaces.risk_metrics` | `packages/core/core/risk/metrics/` |
| Universe filter | `core.universe.UniverseFilter` | `core.universe.universe_filters` | `packages/core/core/filters/` |
| Grouping | `data.v2.analytics.grouping.Grouping` | `data.v2.analytics.grouping.groupings` | `packages/data/data/v2/analytics/grouping.py` |
| Cost model | `core.rebalance.interfaces.CostModel` | `core.rebalance.interfaces.cost_models` | `packages/core/core/rebalance/cost_models/` |
| Rebalance policy | `core.rebalance.interfaces.RebalancePolicy` | `rebalance_policies` | `packages/core/core/rebalance/policies/` |

## Checklist for every extension

1. Add one module in the package shown above.
2. Register it with `@<registry>.register(id=..., name=..., description=...,
   parameter_schema=...)`; expose a Pydantic params model.
3. Add the module to the package `__init__.py` import so importing the package
   registers it.
4. Add a unit test that exercises it **through the registry** (`build_*`).
5. Run `make check` (ruff, mypy, tsc, client-check, pytest, web tests) and add a
   `docs/CHANGELOG.md` entry.

## Worked example 1 — add an Objective (this one ships: `inverse_volatility`)

**File:** `packages/core/core/optimize/objectives/inverse_volatility.py` (39 lines)

```python
"""Objective: closest achievable weights to the inverse-volatility allocation."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from core.optimize.interfaces import OptimizeContext, Vector, objectives


class InverseVolatilityParams(BaseModel):
    """The inverse-volatility objective takes no options."""


@objectives.register(
    id="inverse_volatility",
    name="Inverse volatility",
    description="Minimize distance to inverse-volatility weights (w_i ~ 1 / sigma_i).",
    parameter_schema=InverseVolatilityParams,
)
class InverseVolatility:
    """Squared distance to the inverse-volatility weights ``w_i proportional to 1 / sigma_i``."""

    id = "inverse_volatility"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        InverseVolatilityParams(**(params or {}))

    def _target(self, context: OptimizeContext) -> Vector:
        inverse = 1.0 / np.sqrt(np.maximum(np.diag(context.covariance), 1e-18))
        return inverse / inverse.sum()

    def value(self, weights: Vector, context: OptimizeContext) -> float:
        return float(np.sum((weights - self._target(context)) ** 2))

    def gradient(self, weights: Vector, context: OptimizeContext) -> Vector:
        return 2.0 * (weights - self._target(context))
```

**Registration:** add the module to
`packages/core/core/optimize/objectives/__init__.py`:

```python
from core.optimize.objectives import (
    equal_weight, inverse_volatility, max_sharpe, min_variance,
)
```

**Test:** `packages/core/tests/test_optimize.py` runs it through the engine:

```python
def test_inverse_volatility_is_one_file_and_one_registration() -> None:
    result = _engine(_two_asset_returns(), objective="inverse_volatility")
    assert result.weights["A"] > result.weights["B"]
```

Nothing in the solver, engine or API changed. `GET /api/v1/optimize/options`
now lists `inverse_volatility`, so the Optimize page renders it automatically.

## Worked example 2 — add a Constraint

A constraint returns a vector whose entries must all be `>= 0` (SciPy's
inequality convention). **File:**
`packages/core/core/optimize/constraints/max_position_value.py`

```python
"""Constraint: cap the VND invested in any single position."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from core.optimize.interfaces import OptimizeContext, Vector, constraints


class MaxPositionValueParams(BaseModel):
    max_value: float = Field(default=50_000_000, gt=0, description="Cap per position in VND.")


@constraints.register(
    id="max_position_value",
    name="Maximum position value",
    description="Cap the VND invested in any single position.",
    parameter_schema=MaxPositionValueParams,
)
class MaxPositionValue:
    id = "max_position_value"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._max_value = MaxPositionValueParams(**(params or {})).max_value

    def fun(self, weights: Vector, context: OptimizeContext) -> Vector:
        return np.full(weights.shape, self._max_value / context.investable_capital) - weights

    def capital_reserve_fraction(self) -> float:
        return 0.0
```

**Registration:** add it to
`packages/core/core/optimize/constraints/__init__.py`, then `GET
/api/v1/optimize/options` and the Optimize page constraints builder pick it up.

## Worked example 3 — add a DataProvider

A provider is one file implementing `data.interfaces.DataProvider` (a
`Protocol`). `ProviderBase` supplies HTTP retries, error classification, date
chunking and row parsing. **File:** `packages/data/data/providers/vci.py`

```python
"""VCI (Viet Capital) provider (unofficial)."""

from __future__ import annotations

from datetime import date

from data.models import PriceBar, SymbolInfo
from data.providers.base import ProviderBase
from data.registry import ProviderParams, data_providers


@data_providers.register(
    id="vci",
    name="VCI (unofficial)",
    description="Anonymous VCI public API. Raw (unadjusted) daily OHLCV.",
    parameter_schema=ProviderParams,
)
class VciProvider(ProviderBase):
    id = "vci"
    display_name = "VCI (unofficial)"
    returns_adjusted_prices = False
    supports_indexes = True

    BASE_URL = "https://api.example-vci.vn/"

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        payload = self._get_json(f"{self.BASE_URL}prices/{symbol.upper()}")
        return self._parse_rows(self._rows(payload))

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        payload = self._get_json(f"{self.BASE_URL}index/{index_code.upper()}")
        return self._parse_rows(self._rows(payload))

    def get_index_constituents(self, index_code: str) -> list[str]:
        return [str(code).upper() for code in self._rows(
            self._get_json(f"{self.BASE_URL}groups/{index_code.upper()}")
        )]

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        rows = self._rows(self._get_json(f"{self.BASE_URL}symbols"))
        return [
            SymbolInfo(code=str(row["symbol"]).upper(), exchange=exchange or "HOSE", source=self.id)
            for row in rows
        ]
```

**Registration:** import it in `packages/data/data/providers/__init__.py` and add
`vci` to `PROVIDER_ORDER` (default
`kbs,vci,dnse,tcbs,ssi_iboard`). The failover chain, circuit breaker, sync and
probe read the registry, so no other code changes. Providers must stay
**anonymous**; if an endpoint starts requiring a login, raise `AuthRequiredError`
so the chain fails over.

## Worked example 4 — add a RiskMetric

A metric receives a `RiskContext` (aligned returns, weights, benchmark returns,
dates and the user's `risk_free_rate`) and returns a JSON-serialisable mapping.
The risk-free rate is what the Sharpe, Treynor and Jensen's-alpha metrics use; it
is supplied per request from `UserSettings`, never read from a global. **File:**
`packages/core/core/risk/metrics/downside_deviation.py`

```python
"""Risk metric: downside deviation of the portfolio return stream."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.risk._math import portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="downside_deviation",
    name="Downside deviation",
    description="Annualized standard deviation of the negative portfolio returns only.",
)
class DownsideDeviation:
    id = "downside_deviation"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it takes no parameters."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        portfolio = portfolio_returns(context.returns, context.weights)
        downside = np.minimum(portfolio, 0.0)
        deviation = float(np.sqrt(np.mean(downside**2)) * np.sqrt(context.trading_days))
        return {"downside_deviation": deviation}
```

**Registration:** add it to `packages/core/core/risk/metrics/__init__.py`.
`GET /api/v1/risk/options` lists it and the Risk page renders it.

## Other registries

The remaining concepts follow the identical pattern, so only the hook differs:

- **Universe filters** implement `apply(candidate) -> str | None` and register in
  `packages/core/core/filters/`.
- **Groupings** implement `assign(row) -> str | None` and register in
  `packages/data/data/v2/analytics/grouping.py`; the Sector Analysis sector view is one
  grouping beside the exchange and index-bucket views.
- **Cost models** implement `cost(order, context)` and register in
  `packages/core/core/rebalance/cost_models/`.
- **Rebalance policies** implement `decide(context)` and register in
  `packages/core/core/rebalance/policies/`.

## Removed in V1.1 (may return in V2)

The following concepts were removed in V1.1 while the product is simplified to
CFA Level 1/2 methods. Their extension points are gone with them; each is
documented on `docs/ROADMAP.md` for a possible return in V2.

- Return simulators and the Monte Carlo engine (`block_bootstrap`,
  `multivariate_student_t`; random-portfolio, resampled and forward modes).
- Rebalance schedules, slippage models and backtest metrics (the walk-forward
  backtester).
- Ledoit-Wolf and EWMA return/covariance estimators (sample mean and sample
  covariance only).
- Risk-parity objective, Euler risk contribution and CVaR.
- Max-holdings and ADV-cap constraints (a Portfolio-page liquidity warning
  replaces the ADV cap).

## Deferred features

An item on `docs/ROADMAP.md` may ship its extension point (interface and
registry) but **must not** implement the feature. The roadmap names the exact
registry each V2/V3 item will plug into.

