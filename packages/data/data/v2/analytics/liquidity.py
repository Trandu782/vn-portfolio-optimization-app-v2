"""Liquidity presets and the universe filter (``docs/V2_SPEC.md`` section 4).

The four presets are **config** (thresholds live here and nowhere else). The market-cap
floor is a *full* market-cap floor: free-float is unavailable keyless, so it is
deliberately absent and the ADTV/ADV floors are the real liquidity guards.

Filter semantics
----------------
* Within a facet (sectors, indexes) the match is **OR**.
* Across facets (sector AND index AND exchange) and against the preset the match is
  **AND**. Selecting both VN30 and VN100 is therefore equivalent to VN100 (VN30 is a
  subset of VN100), which is why the spec describes the index chips as ANDed with the
  sector but not necessarily with each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field

from data.v2.analytics.schemas import UniverseRow

_BN = 1_000_000_000.0


@dataclass(frozen=True)
class LiquidityPreset:
    """The thresholds for one retail portfolio-size preset."""

    id: str
    name: str
    portfolio_size_min: float | None
    portfolio_size_max: float | None
    min_adtv: float | None
    min_adv: float | None
    min_market_cap: float | None


#: The four presets, smallest portfolio first. ``all_stocks`` has no thresholds.
LIQUIDITY_PRESETS: tuple[LiquidityPreset, ...] = (
    LiquidityPreset(
        id="small_retail",
        name="Small Retail (< 1B VND)",
        portfolio_size_min=None,
        portfolio_size_max=1 * _BN,
        min_adtv=3 * _BN,
        min_adv=100_000.0,
        min_market_cap=200 * _BN,
    ),
    LiquidityPreset(
        id="standard_retail",
        name="Standard Retail ([1B, 10B) VND)",
        portfolio_size_min=1 * _BN,
        portfolio_size_max=10 * _BN,
        min_adtv=10 * _BN,
        min_adv=150_000.0,
        min_market_cap=500 * _BN,
    ),
    LiquidityPreset(
        id="high_liquidity",
        name="High-Liquidity (>= 10B VND)",
        portfolio_size_min=10 * _BN,
        portfolio_size_max=None,
        min_adtv=30 * _BN,
        min_adv=300_000.0,
        min_market_cap=1_500 * _BN,
    ),
    LiquidityPreset(
        id="all_stocks",
        name="All Stocks",
        portfolio_size_min=None,
        portfolio_size_max=None,
        min_adtv=None,
        min_adv=None,
        min_market_cap=None,
    ),
)

#: The default preset when the caller does not choose one.
DEFAULT_PRESET_ID = "standard_retail"

_PRESET_BY_ID: dict[str, LiquidityPreset] = {
    preset.id: preset for preset in LIQUIDITY_PRESETS
}


def get_preset(preset_id: str) -> LiquidityPreset:
    """Return the preset registered under ``preset_id``.

    Raises:
        KeyError: When ``preset_id`` is unknown.
    """
    key = preset_id.strip().lower()
    try:
        return _PRESET_BY_ID[key]
    except KeyError:
        expected = ", ".join(_PRESET_BY_ID)
        raise KeyError(
            f"unknown liquidity preset {preset_id!r}; expected one of {expected}"
        ) from None


def suggest_preset(portfolio_size: float) -> LiquidityPreset:
    """Return the preset whose portfolio-size range contains ``portfolio_size``."""
    for preset in LIQUIDITY_PRESETS:
        if preset.id == "all_stocks":
            continue
        if preset.portfolio_size_min is not None and portfolio_size < preset.portfolio_size_min:
            continue
        if preset.portfolio_size_max is not None and portfolio_size >= preset.portfolio_size_max:
            continue
        return preset
    return _PRESET_BY_ID["all_stocks"]


class UniverseFilterSpec(BaseModel):
    """The optional sector / index / exchange facets applied on top of the preset."""

    sectors: frozenset[str] = Field(default_factory=frozenset)
    indexes: frozenset[str] = Field(default_factory=frozenset)
    exchange: str | None = None


@dataclass(frozen=True)
class UniverseFilterResult:
    """The kept rows plus every rejected row and its reason."""

    as_of: date | None
    preset_id: str
    kept: list[UniverseRow]
    rejected: list[tuple[UniverseRow, str]]


def _reject_reason(
    row: UniverseRow, preset: LiquidityPreset, spec: UniverseFilterSpec
) -> str | None:
    """Return why ``row`` fails the preset/filters, or ``None`` when it passes."""
    if spec.exchange and row.exchange.strip().upper() != spec.exchange.strip().upper():
        return f"exchange {row.exchange} is not {spec.exchange.strip().upper()}"
    if spec.sectors and (row.sector or "") not in spec.sectors:
        return f"sector {row.sector or 'none'} is not selected"
    selected_indexes = {item.strip().upper() for item in spec.indexes}
    if selected_indexes and not (row.index_memberships & selected_indexes):
        return "not a member of any selected index"
    if preset.min_adtv is not None:
        if row.adtv_median is None:
            return "no ADTV"
        if row.adtv_median < preset.min_adtv:
            return f"ADTV {row.adtv_median:,.0f} VND is below {preset.min_adtv:,.0f}"
    if preset.min_adv is not None:
        if row.adv_median is None:
            return "no ADV"
        if row.adv_median < preset.min_adv:
            return f"ADV {row.adv_median:,.0f} shares is below {preset.min_adv:,.0f}"
    if preset.min_market_cap is not None:
        if row.market_cap is None:
            return "no market cap"
        if row.market_cap < preset.min_market_cap:
            return f"market cap {row.market_cap:,.0f} VND is below {preset.min_market_cap:,.0f}"
    return None


def filter_universe(
    candidates: Sequence[UniverseRow],
    preset_id: str = DEFAULT_PRESET_ID,
    filters: UniverseFilterSpec | None = None,
    *,
    as_of: date | None = None,
) -> UniverseFilterResult:
    """Apply the preset and the optional facets to ``candidates``.

    Args:
        candidates: Universe rows with stored liquidity, market cap, sector and
            index memberships.
        preset_id: A :data:`LIQUIDITY_PRESETS` id (default Standard Retail).
        filters: Optional sector/index/exchange facets.
        as_of: The date the liquidity/market-cap snapshot was taken. Kept in the
            result so the caller can label point-in-time data; the filter itself uses
            the stored per-ticker values.

    Returns:
        A :class:`UniverseFilterResult` with the passing rows and the rejected rows
        paired with a plain-language reason.
    """
    preset = get_preset(preset_id)
    spec = filters or UniverseFilterSpec()
    kept: list[UniverseRow] = []
    rejected: list[tuple[UniverseRow, str]] = []
    for row in candidates:
        reason = _reject_reason(row, preset, spec)
        if reason is None:
            kept.append(row)
        else:
            rejected.append((row, reason))
    return UniverseFilterResult(
        as_of=as_of, preset_id=preset.id, kept=kept, rejected=rejected
    )


__all__ = [
    "DEFAULT_PRESET_ID",
    "LIQUIDITY_PRESETS",
    "LiquidityPreset",
    "UniverseFilterResult",
    "UniverseFilterSpec",
    "filter_universe",
    "get_preset",
    "suggest_preset",
]

