"""Pure domain logic for the VN Portfolio Optimizer.

This package must not import web, database or network libraries. It may only
depend on numpy, pandas and scipy (once statistical features are implemented)
plus pydantic / pydantic-settings for schemas and configuration.
"""

from core import filters as _filters  # noqa: F401  # registers the built-in universe filters
from core import optimize as _optimize  # noqa: F401  # registers the optimizer built-ins
from core import rebalance as _rebalance  # noqa: F401  # registers the rebalance built-ins
from core.costs import commission, round_trip_commission
from core.optimize.engine import optimize as optimize_portfolio
from core.optimize.interfaces import (
    InfeasibleConstraintsError,
    OptimizeAssumptions,
    OptimizeResult,
)
from core.pnl import (
    BuyDateComparison,
    HoldingPnL,
    PnLResult,
    compare_buy_return,
    compute_pnl,
)
from core.portfolio import (
    Holding,
    Portfolio,
    PortfolioValuation,
    portfolio_value_and_weights,
)
from core.rebalance import (
    RebalanceOrder,
    RebalanceResult,
    cost_models,
    rebalance_policies,
)
from core.rebalance import rebalance as rebalance_portfolio
from core.registry import Registry, RegistryInfo
from core.risk import compute_risk, risk_metrics, sharpe_ratio
from core.settings import UserSettings
from core.universe import (
    DailyBar,
    DroppedTicker,
    FilterSpec,
    QualityFlags,
    SymbolSeries,
    UniverseBuildResult,
    UniverseFilter,
    average_daily_value,
    build_filter,
    build_filters,
    build_universe,
    normalize_exchange,
    traded_value,
    universe_filters,
)
from core.validation import (
    MAX_CHUNKS,
    MIN_MARKET_DATE,
    TICKER_SYMBOL_PATTERN,
    TICKER_SYMBOL_RE,
    FiniteFloat,
    MarketDate,
    TickerSymbol,
    format_validation_error,
    validate_finite_float,
    validate_market_date,
    validate_ticker_symbol,
)

__all__ = [
    "MAX_CHUNKS",
    "MIN_MARKET_DATE",
    "TICKER_SYMBOL_PATTERN",
    "TICKER_SYMBOL_RE",
    "BuyDateComparison",
    "DailyBar",
    "DroppedTicker",
    "FilterSpec",
    "FiniteFloat",
    "Holding",
    "HoldingPnL",
    "InfeasibleConstraintsError",
    "MarketDate",
    "OptimizeAssumptions",
    "OptimizeResult",
    "PnLResult",
    "Portfolio",
    "PortfolioValuation",
    "QualityFlags",
    "RebalanceOrder",
    "RebalanceResult",
    "Registry",
    "RegistryInfo",
    "SymbolSeries",
    "TickerSymbol",
    "UniverseBuildResult",
    "UniverseFilter",
    "UserSettings",
    "average_daily_value",
    "build_filter",
    "build_filters",
    "build_universe",
    "commission",
    "compare_buy_return",
    "compute_pnl",
    "compute_risk",
    "cost_models",
    "format_validation_error",
    "normalize_exchange",
    "optimize_portfolio",
    "portfolio_value_and_weights",
    "rebalance_policies",
    "rebalance_portfolio",
    "risk_metrics",
    "round_trip_commission",
    "sharpe_ratio",
    "traded_value",
    "universe_filters",
    "validate_finite_float",
    "validate_market_date",
    "validate_ticker_symbol",
]
__version__ = "0.1.0"
