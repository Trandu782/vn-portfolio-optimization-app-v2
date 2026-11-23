"""Product guardrails for the simplified optimizer.

Pure helpers with no registry: the default per-position weight cap and the
universe-size warnings/limit for the guided Optimize page. They live here (not in
the web layer) so the API can enforce the same rules and both are unit-tested
without a browser.
"""

from __future__ import annotations

#: Below this many stocks the efficient frontier is not meaningful.
MIN_MEANINGFUL_STOCKS = 5
#: Above this many stocks the sample covariance is unreliable.
MAX_RELIABLE_STOCKS = 20
#: Hard cap on the number of stocks in one optimization.
HARD_MAX_STOCKS = 30
#: Floor of the default weight cap, regardless of the portfolio size.
DEFAULT_MAX_WEIGHT_FLOOR = 0.25
#: The default cap is at least this many equal slices (1.5 / n).
DEFAULT_MAX_WEIGHT_MULTIPLE = 1.5


def default_max_weight(n_assets: int) -> float:
    """Return the default per-position weight cap for ``n_assets`` stocks.

    The cap is ``max(25%, 1.5 / n)``, capped at 100% for a single stock, so a
    small portfolio can still be fully invested without the cap binding.
    """
    if n_assets <= 0:
        return DEFAULT_MAX_WEIGHT_FLOOR
    return min(1.0, max(DEFAULT_MAX_WEIGHT_FLOOR, DEFAULT_MAX_WEIGHT_MULTIPLE / n_assets))


def feasible_max_weight(n_assets: int, requested: float) -> tuple[float, bool]:
    """Return a feasible cap and whether the requested cap had to be raised.

    A cap makes full investment impossible when ``n * cap < 1``; in that case the
    cap is raised to ``1 / n`` so the optimizer can deploy 100% of the capital.
    """
    if n_assets <= 0:
        return requested, False
    minimum = 1.0 / n_assets
    if requested * n_assets < 1.0:
        return minimum, True
    return requested, False


def universe_size_warnings(n_assets: int) -> list[str]:
    """Return plain-language warnings for a universe of ``n_assets`` stocks."""
    warnings: list[str] = []
    if n_assets < MIN_MEANINGFUL_STOCKS:
        warnings.append(
            f"Only {n_assets} stock(s): the efficient frontier is not meaningful "
            f"below {MIN_MEANINGFUL_STOCKS}."
        )
    if n_assets > MAX_RELIABLE_STOCKS:
        warnings.append(
            f"{n_assets} stocks is a lot: the sample covariance becomes unreliable "
            f"above {MAX_RELIABLE_STOCKS}."
        )
    return warnings


def exceeds_hard_max(n_assets: int) -> bool:
    """Return True when ``n_assets`` exceeds the hard cap."""
    return n_assets > HARD_MAX_STOCKS
