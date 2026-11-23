"""Built-in trading cost models.

Importing this package registers every cost model in
:data:`core.rebalance.interfaces.cost_models`. Adding one is a new module in this
package plus one ``@cost_models.register`` call.
"""

from __future__ import annotations

from core.rebalance.cost_models import vn

__all__ = ["vn"]
