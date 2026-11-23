"""Built-in solvers.

Importing this package registers every solver in
:data:`core.optimize.interfaces.solvers`. Adding a solver (for example a QP
solver) is a new module plus one ``@register`` call; objectives and constraints do
not change.
"""

from __future__ import annotations

from core.optimize.solvers import scipy_slsqp

__all__ = ["scipy_slsqp"]
