"""Built-in portfolio objectives.

Importing this package registers every objective in
:data:`core.optimize.interfaces.objectives`. Adding an objective is one new module
in this package plus one ``@register`` call; the solver and the engine never learn
about a specific objective.
"""

from __future__ import annotations

from core.optimize.objectives import (
    equal_weight,
    inverse_volatility,
    max_sharpe,
    min_variance,
)

__all__ = ["equal_weight", "inverse_volatility", "max_sharpe", "min_variance"]
