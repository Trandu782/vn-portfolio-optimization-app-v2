"""Built-in rebalance policies.

Importing this package registers every policy in
:data:`core.rebalance.interfaces.rebalance_policies`. Adding one is a new module in
this package plus one ``@rebalance_policies.register`` call.
"""

from __future__ import annotations

from core.rebalance.policies import full, threshold_band

__all__ = ["full", "threshold_band"]
