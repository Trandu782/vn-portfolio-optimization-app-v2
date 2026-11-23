"""Built-in return estimators.

Importing this package registers every estimator in
:data:`core.optimize.interfaces.return_estimators`. Adding one is a new module in
this package plus one ``@register`` call.
"""

from __future__ import annotations

from core.optimize.return_estimators import historical_mean

__all__ = ["historical_mean"]
