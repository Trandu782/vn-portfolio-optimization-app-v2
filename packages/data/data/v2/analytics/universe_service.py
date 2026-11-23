"""Read-only universe filtering and sector listing over the stored V2 tables.

This is the one data-layer helper behind ``GET /v2/universe`` and ``GET /v2/sectors``.
It reads only the V2 tables (never the network), calls the same
:func:`data.v2.analytics.liquidity.filter_universe` the Sector Analysis engine uses,
and returns typed payloads with ``data_as_of`` and the basis flags. The routes stay
thin: they build a request, call one method here and map ``ValueError`` to a 422.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import session_scope
from data.v2.analytics.liquidity import (
    DEFAULT_PRESET_ID,
    UniverseFilterSpec,
    filter_universe,
    get_preset,
)
from data.v2.analytics.schemas import AdjustmentQualityFlag
from data.v2.analytics.universe_reader import (
    join_labels,
    load_adjustment_flags,
    load_universe_snapshot,
)
from data.v2.store import V2Store

#: Index codes the universe facet accepts.
VALID_INDEXES: frozenset[str] = frozenset({"VN30", "VN100"})
#: Exchange codes the universe facet accepts (UPCoM is stored as ``UPCOM``).
VALID_EXCHANGES: frozenset[str] = frozenset({"HOSE", "HNX", "UPCOM"})

_MARKET_CAP_NOTE = (
    "Full market cap (free-float is unavailable keyless; ADTV and ADV are the "
    "real liquidity guards)."
)
_UNAVAILABLE = "V2 data not available: run the precompute job to populate it."


class V2Basis(BaseModel):
    """The basis flags for the datasets behind one universe response."""

    model_config = ConfigDict(frozen=True)

    price_adjustment_basis: str | None = None
    volume_basis: str | None = None
    market_cap_basis: str = "full"
    market_cap_note: str = _MARKET_CAP_NOTE


class V2UniverseTicker(BaseModel):
    """One ticker that passed the preset and facet filters."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: str
    sector: str | None = None
    index_memberships: list[str] = Field(default_factory=list)
    adtv_median: float | None = None
    adv_median: float | None = None
    market_cap: float | None = None
    volume_basis: str | None = None


class V2RejectedTicker(BaseModel):
    """One ticker that failed the filter, with a plain-language reason."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    reason: str


class UniverseFilterRequest(BaseModel):
    """The universe filter facets (sector/index/exchange plus the preset)."""

    preset: str = DEFAULT_PRESET_ID
    sectors: list[str] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)
    exchange: str | None = None
    as_of: date | None = None
    exclude_adjustment_flagged: bool = False


class UniverseFilterResponse(BaseModel):
    """The kept/rejected universe plus provenance, warnings and stored flags."""

    model_config = ConfigDict(frozen=True)

    available: bool
    data_as_of: date | None = None
    preset_id: str = DEFAULT_PRESET_ID
    basis: V2Basis = Field(default_factory=V2Basis)
    kept: list[V2UniverseTicker] = Field(default_factory=list)
    rejected: list[V2RejectedTicker] = Field(default_factory=list)
    adjustment_flags: list[AdjustmentQualityFlag] = Field(default_factory=list)
    flags_available: bool = False
    flags_policy_current: bool = False
    warnings: list[str] = Field(default_factory=list)


class V2SectorCount(BaseModel):
    """One ICB level-2 sector with total and preset-passing constituent counts."""

    model_config = ConfigDict(frozen=True)

    name: str
    total: int
    passing: int


class SectorListResponse(BaseModel):
    """The sector list (for the multi-select) with counts and provenance."""

    model_config = ConfigDict(frozen=True)

    available: bool
    data_as_of: date | None = None
    preset_id: str = DEFAULT_PRESET_ID
    sectors: list[V2SectorCount] = Field(default_factory=list)
    total_without_sector: int = 0
    warnings: list[str] = Field(default_factory=list)


def _normalize(value: str) -> str:
    return value.strip().upper()


class UniverseService:
    """Assemble the universe-filter and sector-list responses from V2 data."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _validated_indexes(self, indexes: list[str]) -> set[str]:
        normalized = {_normalize(item) for item in indexes if item.strip()}
        unknown = normalized - VALID_INDEXES
        if unknown:
            raise ValueError(
                f"unknown index(es) {sorted(unknown)}; expected one of {sorted(VALID_INDEXES)}"
            )
        return normalized

    def _validated_exchange(self, exchange: str | None) -> str | None:
        if not exchange or not exchange.strip():
            return None
        normalized = _normalize(exchange)
        if normalized not in VALID_EXCHANGES:
            raise ValueError(
                f"unknown exchange {exchange!r}; expected one of {sorted(VALID_EXCHANGES)}"
            )
        return normalized

    def filter(self, request: UniverseFilterRequest) -> UniverseFilterResponse:
        """Apply the preset and facets exactly as ``filter_universe`` does.

        Raises:
            ValueError: When the preset, an index code, the exchange or a sector name
                is unknown (the route maps this to a 422).
        """
        try:
            get_preset(request.preset)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        indexes = self._validated_indexes(request.indexes)
        exchange = self._validated_exchange(request.exchange)

        snapshot = load_universe_snapshot(self._session_factory)
        if not snapshot.master:
            return UniverseFilterResponse(
                available=False, preset_id=request.preset, warnings=[_UNAVAILABLE]
            )

        selected_sectors = {item.strip() for item in request.sectors if item.strip()}
        unknown_sectors = selected_sectors - set(snapshot.sector_by_ticker.values())
        if unknown_sectors:
            raise ValueError(
                f"unknown sector(s) {sorted(unknown_sectors)}; use GET /v2/sectors "
                "for the available names"
            )

        data_as_of = request.as_of or snapshot.latest_price_date
        filtered = filter_universe(
            snapshot.rows,
            request.preset,
            UniverseFilterSpec(
                sectors=frozenset(selected_sectors),
                indexes=frozenset(indexes),
                exchange=exchange,
            ),
            as_of=data_as_of,
        )
        stored_flags, flags_available, flags_policy_current = load_adjustment_flags(
            self._session_factory
        )
        warnings: list[str] = []

        kept_rows = filtered.kept
        if request.exclude_adjustment_flagged:
            if flags_available:
                remaining = []
                excluded = 0
                for row in kept_rows:
                    flag = stored_flags.get(row.ticker)
                    if flag is not None and flag.flagged:
                        excluded += 1
                    else:
                        remaining.append(row)
                kept_rows = remaining
                if excluded:
                    warnings.append(
                        f"Excluded {excluded} ticker(s) with adjustment-quality flags."
                    )
            else:
                warnings.append(
                    "exclude_adjustment_flagged was requested but the flags have not "
                    "been computed yet; the flags were ignored."
                )

        if not kept_rows:
            warnings.append("no tickers pass the selected filters")
        if snapshot.sector_gaps:
            preview = ", ".join(snapshot.sector_gaps[:20])
            warnings.append(
                f"{len(snapshot.sector_gaps)} ticker(s) have no ICB level-2 sector and "
                f"are excluded from sector filters: {preview}"
            )

        flagged = [
            stored_flags[row.ticker]
            for row in kept_rows
            if row.ticker in stored_flags and stored_flags[row.ticker].flagged
        ]
        if flags_available:
            if flagged:
                warnings.append(
                    f"{len(flagged)} ticker(s) have adjustment-quality flags; set "
                    "exclude_adjustment_flagged=true to drop them."
                )
            if not flags_policy_current:
                warnings.append(
                    "Adjustment-quality flags were computed under an older policy; "
                    "rerun the update (or the --recompute-flags job) to refresh them."
                )
        else:
            warnings.append(
                "Adjustment-quality flags have not been computed yet; run the "
                "precompute job to populate them."
            )

        price_basis = join_labels(
            [snapshot.price_adjustment_bases.get(row.ticker, "") for row in kept_rows]
        )
        volume_basis = join_labels(
            [
                snapshot.liquidity[row.ticker].volume_basis
                for row in kept_rows
                if row.ticker in snapshot.liquidity
            ]
        )
        if price_basis and price_basis != "ssi_adjusted":
            warnings.append(
                f"Prices use the {price_basis} adjustment basis (a fallback); treat "
                "returns with caution."
            )

        with session_scope(self._session_factory) as session:
            starts = V2Store(session).history_starts()
        missing_history = [row.ticker for row in kept_rows if row.ticker not in starts]
        if missing_history:
            warnings.append(
                f"{len(missing_history)} ticker(s) have no stored price history "
                "(partial data)."
            )

        return UniverseFilterResponse(
            available=True,
            data_as_of=data_as_of,
            preset_id=filtered.preset_id,
            basis=V2Basis(
                price_adjustment_basis=price_basis,
                volume_basis=volume_basis,
                market_cap_basis="full",
            ),
            kept=[
                V2UniverseTicker(
                    ticker=row.ticker,
                    exchange=row.exchange,
                    sector=row.sector,
                    index_memberships=sorted(row.index_memberships),
                    adtv_median=row.adtv_median,
                    adv_median=row.adv_median,
                    market_cap=row.market_cap,
                    volume_basis=row.volume_basis,
                )
                for row in kept_rows
            ],
            rejected=[
                V2RejectedTicker(ticker=row.ticker, reason=reason)
                for row, reason in filtered.rejected
            ],
            adjustment_flags=flagged,
            flags_available=flags_available,
            flags_policy_current=flags_policy_current,
            warnings=warnings,
        )

    def sectors(self, preset: str = DEFAULT_PRESET_ID) -> SectorListResponse:
        """Return every ICB level-2 sector with total and preset-passing counts."""
        try:
            get_preset(preset)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        snapshot = load_universe_snapshot(self._session_factory)
        if not snapshot.master:
            return SectorListResponse(
                available=False, preset_id=preset, warnings=[_UNAVAILABLE]
            )
        passing = filter_universe(
            snapshot.rows, preset, UniverseFilterSpec(), as_of=snapshot.latest_price_date
        )
        total_by_sector: dict[str, int] = {}
        for row in snapshot.rows:
            if row.sector:
                total_by_sector[row.sector] = total_by_sector.get(row.sector, 0) + 1
        passing_by_sector: dict[str, int] = {}
        for row in passing.kept:
            if row.sector:
                passing_by_sector[row.sector] = passing_by_sector.get(row.sector, 0) + 1
        return SectorListResponse(
            available=True,
            data_as_of=snapshot.latest_price_date,
            preset_id=passing.preset_id,
            sectors=[
                V2SectorCount(
                    name=name, total=total, passing=passing_by_sector.get(name, 0)
                )
                for name, total in sorted(total_by_sector.items())
            ],
            total_without_sector=len(snapshot.sector_gaps),
        )


__all__ = [
    "SectorListResponse",
    "UniverseFilterRequest",
    "UniverseFilterResponse",
    "UniverseService",
    "V2Basis",
    "V2RejectedTicker",
    "V2SectorCount",
    "V2UniverseTicker",
]




