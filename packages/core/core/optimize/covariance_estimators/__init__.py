"""Built-in covariance estimators.

Importing this package registers every estimator in
:data:`core.optimize.interfaces.covariance_estimators`. Adding one is a new module
in this package plus one ``@register`` call.
"""

from __future__ import annotations

from core.optimize.covariance_estimators import sample

__all__ = ["sample"]
