"""Built-in portfolio constraints.

Importing this package registers every constraint in
:data:`core.optimize.interfaces.constraints`. Each constraint returns values that
must be ``>= 0`` (the scipy inequality convention). Adding one is a new module in
this package plus one ``@register`` call.

Long-only (weights ``>= 0``) and fully invested (weights sum to 1) are always
enforced by the solver; the constraints here are the optional extras.
"""

from __future__ import annotations

from core.optimize.constraints import cash_reserve, max_sector_weight, max_weight

__all__ = ["cash_reserve", "max_sector_weight", "max_weight"]
