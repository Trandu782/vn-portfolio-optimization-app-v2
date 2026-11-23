"""Built-in risk metrics.

Importing this package registers every metric in
:data:`core.risk.interfaces.risk_metrics`. Adding one is a new module in this
package plus one ``@risk_metrics.register`` call.
"""

from __future__ import annotations

from core.risk.metrics import (
    annualized_volatility,
    beta,
    correlation_matrix,
    historical_var,
    jensens_alpha,
    max_drawdown,
    sharpe,
    treynor,
)

__all__ = [
    "annualized_volatility",
    "beta",
    "correlation_matrix",
    "historical_var",
    "jensens_alpha",
    "max_drawdown",
    "sharpe",
    "treynor",
]
