"""Repository over the V2 precompute tables.

One small class wraps a SQLAlchemy :class:`~sqlalchemy.orm.Session` and exposes the
upsert/read operations the pipeline and the reader need. Upserts are idempotent
(``ON CONFLICT`` on SQLite and Postgres, via the shared helper in
``data.db.repositories``), so re-running the pipeline never duplicates a row.

Every write records provenance (``source``) and the run date (``data_as_of``), and the
price rows keep the per-bar adjustment/volume basis flags. This is the storage choice
recorded in ``docs/DECISIONS.md``: the repo's existing SQLAlchemy + SQLite/Postgres +
Alembic stack, with V2 data in additive tables so V1 is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from data.db.models import (
    V2AdjustmentFlag,
    V2CorporateAction,
    V2DailyPrice,
    V2FinancialRatio,
    V2Liquidity,
    V2MarketCap,
    V2Membership,
    V2Progress,
    V2SectorMap,
    V2SectorStatistic,
    V2TickerMaster,
)
from data.db.repositories import SqlIndexRepository, _bulk_upsert
from data.v2.precompute_schemas import (
    AdjustmentAnomalyRecord,
    AdjustmentFlagRecord,
    LiquidityRecord,
    MarketCapRecord,
    ProgressRecord,
    RatioRecord,
    SectorStatisticRecord,
    TickerRecord,
)
from data.v2.schemas import AdjustedOHLCV, CorporateAction, SectorMap

#: Basis written when a provider separates order-matching flow.
_VOLUME_MATCHED = "matched"
#: Basis written when only total volume is available.
_VOLUME_TOTAL = "total"


def _ticker_record(row: V2TickerMaster) -> TickerRecord:
    return TickerRecord(
        ticker=row.ticker,
        exchange=row.exchange,
        name=row.name,
        security_type=row.security_type,
        source=row.source,
        data_as_of=row.data_as_of,
    )


def _sector_record(row: V2SectorMap) -> SectorMap:
    return SectorMap(
        ticker=row.ticker,
        exchange="",
        icb_level2_name=row.icb_level2_name,
        icb_level2_code=row.icb_level2_code,
        source=row.source,
        as_of=row.as_of,
    )


def _price_bar(row: V2DailyPrice) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=row.date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close_adj,
        close_raw=row.close_raw,
        volume=row.volume,
        matched_volume=row.matched_volume,
        matched_value=row.matched_value,
        value=row.value,
        source=row.source,
    )


def _liquidity_record(row: V2Liquidity) -> LiquidityRecord:
    return LiquidityRecord(
        symbol=row.symbol_code,
        as_of=row.as_of,
        adtv_median=row.adtv_median,
        adv_median=row.adv_median,
        window=row.window,
        volume_basis=row.volume_basis,  # type: ignore[arg-type]
        source=row.source,
        data_as_of=row.data_as_of,
    )


def _market_cap_record(row: V2MarketCap) -> MarketCapRecord:
    return MarketCapRecord(
        symbol=row.symbol_code,
        as_of=row.as_of,
        shares_outstanding=row.shares_outstanding,
        market_cap=row.market_cap,
        basis=row.basis,  # type: ignore[arg-type]
        source=row.source,
        data_as_of=row.data_as_of,
    )


def _adjustment_flag_record(row: V2AdjustmentFlag) -> AdjustmentFlagRecord:
    return AdjustmentFlagRecord(
        ticker=row.ticker,
        severity=row.severity,  # type: ignore[arg-type]
        flagged=row.flagged,
        exclude_from_group_indices=row.exclude_from_group_indices,
        reasons=list(row.reasons or []),
        dates=[date.fromisoformat(value) for value in (row.dates or [])],
        anomalies=_anomaly_records(row.anomalies),
        source=row.source,
        data_as_of=row.data_as_of,
    )


def _anomaly_records(
    raw: list[dict[str, object]] | None,
) -> list[AdjustmentAnomalyRecord]:
    """Decode the stored per-anomaly JSON into typed records (skipping bad rows)."""
    records: list[AdjustmentAnomalyRecord] = []
    for item in raw or []:
        day = item.get("date")
        if not isinstance(day, str):
            continue
        category: Literal["data_glitch", "thin_trading"] = (
            "thin_trading" if item.get("category") == "thin_trading" else "data_glitch"
        )
        raw_reason = item.get("reason")
        records.append(
            AdjustmentAnomalyRecord(
                date=date.fromisoformat(day),
                exclude=bool(item.get("exclude", False)),
                category=category,
                reason=raw_reason if isinstance(raw_reason, str) else "",
            )
        )
    return records


def _progress_record(row: V2Progress) -> ProgressRecord:
    return ProgressRecord(
        kind=row.kind,
        symbol=row.symbol,
        state=row.state,
        last_date=row.last_date,
        rows=row.rows,
        error=row.error,
    )


def _action_record(row: V2CorporateAction) -> CorporateAction:
    return CorporateAction(
        ticker=row.ticker,
        event_type=row.event_type,
        exright_date=row.exright_date,
        record_date=row.record_date,
        ratio=row.ratio,
        value=row.value,
        source=row.source,
    )


def _ratio_record(row: V2FinancialRatio) -> RatioRecord:
    return RatioRecord(
        symbol=row.symbol_code,
        period=row.period,
        period_type=row.period_type,  # type: ignore[arg-type]
        ratio_group=row.ratio_group,  # type: ignore[arg-type]
        ratios=dict(row.ratios or {}),
        source=row.source,
        data_as_of=row.data_as_of,
    )


def _sector_statistic_record(row: V2SectorStatistic) -> SectorStatisticRecord:
    return SectorStatisticRecord(
        sector=row.sector,
        ratio=row.ratio,
        period=row.period,
        period_type=row.period_type,  # type: ignore[arg-type]
        n=row.n,
        median=row.median,
        mean=row.mean,
        winsorized_mean=row.winsorized_mean,
        p5=row.p5,
        p95=row.p95,
        minimum=row.minimum,
        maximum=row.maximum,
        percentile_ranks=dict(row.percentile_ranks or {}),
        source=row.source,
        data_as_of=row.data_as_of,
    )


class V2Store:
    """Read/write access to the V2 precompute tables for one session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- ticker master / sectors -------------------------------------------
    def upsert_ticker_master(self, records: Sequence[TickerRecord]) -> int:
        """Upsert the cleaned universe, replacing stale metadata."""
        rows = [
            {
                "ticker": record.ticker,
                "exchange": record.exchange,
                "name": record.name,
                "security_type": record.security_type,
                "source": record.source,
                "data_as_of": record.data_as_of,
            }
            for record in records
        ]
        return _bulk_upsert(
            self._session,
            V2TickerMaster,
            rows,
            key_columns=["ticker"],
            update_columns=["exchange", "name", "security_type", "source", "data_as_of"],
        )

    def list_ticker_master(self) -> list[TickerRecord]:
        """Return the stored universe, sorted by ticker."""
        statement = select(V2TickerMaster).order_by(V2TickerMaster.ticker)
        return [_ticker_record(row) for row in self._session.scalars(statement)]

    # -- trading calendar --------------------------------------------------
    def list_index_dates(self, index_code: str = "VNINDEX") -> list[date]:
        """Return the stored bar dates for an index (the trading-calendar source).

        Pass the result to :func:`data.calendar.trading_days_from_dates` to derive the
        real exchange calendar from benchmark bars instead of a hardcoded holiday set.
        """
        repository = SqlIndexRepository(self._session)
        earliest = repository.earliest_date(index_code)
        latest = repository.latest_date(index_code)
        if earliest is None or latest is None:
            return []
        return [bar.date for bar in repository.get_range(index_code, earliest, latest)]

    def upsert_sectors(self, records: Sequence[SectorMap]) -> int:
        """Upsert the ICB level-2 map for the universe."""
        rows = [
            {
                "ticker": record.ticker,
                "icb_level2_name": record.icb_level2_name or "",
                "icb_level2_code": record.icb_level2_code,
                "source": record.source,
                "as_of": record.as_of or date.min,
            }
            for record in records
            if record.icb_level2_name
        ]
        return _bulk_upsert(
            self._session,
            V2SectorMap,
            rows,
            key_columns=["ticker"],
            update_columns=["icb_level2_name", "icb_level2_code", "source", "as_of"],
        )

    def get_sector(self, ticker: str) -> SectorMap | None:
        """Return one ticker's sector, or ``None`` when it is a coverage gap."""
        row = self._session.get(V2SectorMap, ticker.upper())
        return _sector_record(row) if row is not None else None

    def list_sectors(self) -> list[SectorMap]:
        """Return every stored sector row, sorted by ticker."""
        statement = select(V2SectorMap).order_by(V2SectorMap.ticker)
        return [_sector_record(row) for row in self._session.scalars(statement)]

    # -- index membership --------------------------------------------------
    def replace_membership(
        self, index_code: str, codes: Sequence[str], *, as_of: date, source: str
    ) -> int:
        """Replace one index's membership with ``codes`` at ``as_of``."""
        code = index_code.upper()
        self._session.execute(delete(V2Membership).where(V2Membership.index_code == code))
        unique = list(dict.fromkeys(item.strip().upper() for item in codes if item.strip()))
        rows = [
            {"index_code": code, "symbol_code": symbol, "as_of": as_of, "source": source}
            for symbol in unique
        ]
        return _bulk_upsert(
            self._session,
            V2Membership,
            rows,
            key_columns=["index_code", "symbol_code"],
            update_columns=["as_of", "source"],
        )

    def get_membership(self, index_code: str) -> list[str]:
        """Return one index's stored members, sorted."""
        statement = (
            select(V2Membership.symbol_code)
            .where(V2Membership.index_code == index_code.upper())
            .order_by(V2Membership.symbol_code)
        )
        return list(self._session.scalars(statement))

    # -- daily prices ------------------------------------------------------
    def upsert_prices(
        self,
        symbol: str,
        bars: Sequence[AdjustedOHLCV],
        *,
        price_adjustment_basis: str,
        data_as_of: date,
    ) -> int:
        """Upsert daily bars with their per-bar volume basis and provenance."""
        code = symbol.upper()
        rows = [
            {
                "symbol_code": code,
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close_adj": bar.close,
                "close_raw": bar.close_raw,
                "volume": bar.volume,
                "matched_volume": bar.matched_volume,
                "matched_value": bar.matched_value,
                "value": bar.value,
                "price_adjustment_basis": price_adjustment_basis,
                "volume_basis": (
                    _VOLUME_MATCHED if bar.matched_volume is not None else _VOLUME_TOTAL
                ),
                "source": bar.source,
                "data_as_of": data_as_of,
            }
            for bar in bars
        ]
        return _bulk_upsert(
            self._session,
            V2DailyPrice,
            rows,
            key_columns=["symbol_code", "date"],
            update_columns=[
                "open",
                "high",
                "low",
                "close_adj",
                "close_raw",
                "volume",
                "matched_volume",
                "matched_value",
                "value",
                "price_adjustment_basis",
                "volume_basis",
                "source",
                "data_as_of",
            ],
        )

    def get_prices(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[AdjustedOHLCV]:
        """Return stored bars for ``symbol`` in ``[start, end]``, sorted by date."""
        statement = select(V2DailyPrice).where(V2DailyPrice.symbol_code == symbol.upper())
        if start is not None:
            statement = statement.where(V2DailyPrice.date >= start)
        if end is not None:
            statement = statement.where(V2DailyPrice.date <= end)
        statement = statement.order_by(V2DailyPrice.date)
        return [_price_bar(row) for row in self._session.scalars(statement)]

    def latest_price_date(self, symbol: str) -> date | None:
        """Return the newest stored bar date for ``symbol`` (or ``None``)."""
        return self._session.scalar(
            select(func.max(V2DailyPrice.date)).where(
                V2DailyPrice.symbol_code == symbol.upper()
            )
        )

    def earliest_price_date(self, symbol: str) -> date | None:
        """Return the oldest stored bar date for ``symbol`` (or ``None``)."""
        return self._session.scalar(
            select(func.min(V2DailyPrice.date)).where(
                V2DailyPrice.symbol_code == symbol.upper()
            )
        )

    def count_prices(self, symbol: str) -> int:
        """Return the number of stored bars for ``symbol``."""
        total = self._session.scalar(
            select(func.count())
            .select_from(V2DailyPrice)
            .where(V2DailyPrice.symbol_code == symbol.upper())
        )
        return int(total or 0)

    def latest_source(self) -> str | None:
        """Return the source of the newest stored bar across every ticker (or ``None``)."""
        return self._session.scalar(
            select(V2DailyPrice.source)
            .order_by(V2DailyPrice.date.desc())
            .limit(1)
        )

    def latest_price_meta(
        self, symbol: str
    ) -> tuple[str | None, str | None, date | None]:
        """Return ``(source, price_adjustment_basis, data_as_of)`` of the newest bar."""
        statement = (
            select(V2DailyPrice)
            .where(V2DailyPrice.symbol_code == symbol.upper())
            .order_by(V2DailyPrice.date.desc())
            .limit(1)
        )
        row = self._session.scalars(statement).first()
        if row is None:
            return None, None, None
        return row.source, row.price_adjustment_basis, row.data_as_of

    # -- liquidity / market cap -------------------------------------------
    def upsert_liquidity(self, record: LiquidityRecord) -> int:
        """Upsert one ticker's rolling-median liquidity."""
        return _bulk_upsert(
            self._session,
            V2Liquidity,
            [
                {
                    "symbol_code": record.symbol.upper(),
                    "as_of": record.as_of,
                    "adtv_median": record.adtv_median,
                    "adv_median": record.adv_median,
                    "window": record.window,
                    "volume_basis": record.volume_basis,
                    "source": record.source,
                    "data_as_of": record.data_as_of,
                }
            ],
            key_columns=["symbol_code"],
            update_columns=[
                "as_of",
                "adtv_median",
                "adv_median",
                "window",
                "volume_basis",
                "source",
                "data_as_of",
            ],
        )

    def get_liquidity(self, symbol: str) -> LiquidityRecord | None:
        """Return one ticker's stored liquidity, or ``None``."""
        row = self._session.get(V2Liquidity, symbol.upper())
        return _liquidity_record(row) if row is not None else None

    def upsert_market_cap(self, record: MarketCapRecord) -> int:
        """Upsert one ticker's shares outstanding and full market cap."""
        return _bulk_upsert(
            self._session,
            V2MarketCap,
            [
                {
                    "symbol_code": record.symbol.upper(),
                    "as_of": record.as_of,
                    "shares_outstanding": record.shares_outstanding,
                    "market_cap": record.market_cap,
                    "basis": record.basis,
                    "source": record.source,
                    "data_as_of": record.data_as_of,
                }
            ],
            key_columns=["symbol_code"],
            update_columns=[
                "as_of",
                "shares_outstanding",
                "market_cap",
                "basis",
                "source",
                "data_as_of",
            ],
        )

    def get_market_cap(self, symbol: str) -> MarketCapRecord | None:
        """Return one ticker's stored market cap, or ``None``."""
        row = self._session.get(V2MarketCap, symbol.upper())
        return _market_cap_record(row) if row is not None else None

    # -- corporate actions -------------------------------------------------
    def replace_corporate_actions(
        self, ticker: str, actions: Sequence[CorporateAction], *, data_as_of: date
    ) -> int:
        """Replace one ticker's stored DIV/ISS events (idempotent per ticker)."""
        code = ticker.upper()
        self._session.execute(delete(V2CorporateAction).where(V2CorporateAction.ticker == code))
        rows = [
            {
                "ticker": code,
                "event_type": action.event_type,
                "exright_date": action.exright_date,
                "record_date": action.record_date,
                "ratio": action.ratio,
                "value": action.value,
                "source": action.source,
                "data_as_of": data_as_of,
            }
            for action in actions
            if action.event_type in {"DIV", "ISS"}
        ]
        if not rows:
            return 0
        self._session.add_all([V2CorporateAction(**row) for row in rows])
        self._session.flush()
        return len(rows)

    def get_corporate_actions(self, ticker: str) -> list[CorporateAction]:
        """Return one ticker's stored corporate actions, ordered by ex-date."""
        statement = (
            select(V2CorporateAction)
            .where(V2CorporateAction.ticker == ticker.upper())
            .order_by(V2CorporateAction.exright_date)
        )
        return [_action_record(row) for row in self._session.scalars(statement)]

    # -- progress / checkpoints -------------------------------------------
    def get_progress(self, kind: str, symbol: str) -> ProgressRecord | None:
        """Return one checkpoint, or ``None`` when the unit has never run."""
        row = self._session.get(V2Progress, (kind, symbol.upper()))
        return _progress_record(row) if row is not None else None

    def set_progress(self, record: ProgressRecord) -> int:
        """Upsert one checkpoint (state, last committed date, row count, error)."""
        return _bulk_upsert(
            self._session,
            V2Progress,
            [
                {
                    "kind": record.kind,
                    "symbol": record.symbol.upper(),
                    "state": record.state,
                    "last_date": record.last_date,
                    "rows": record.rows,
                    "error": record.error,
                }
            ],
            key_columns=["kind", "symbol"],
            update_columns=["state", "last_date", "rows", "error"],
        )

    def list_progress(self, kind: str) -> list[ProgressRecord]:
        """Return every checkpoint for ``kind``, sorted by ticker."""
        statement = (
            select(V2Progress)
            .where(V2Progress.kind == kind)
            .order_by(V2Progress.symbol)
        )
        return [_progress_record(row) for row in self._session.scalars(statement)]

    # -- analytics helpers -------------------------------------------------
    def list_liquidity(self) -> list[LiquidityRecord]:
        """Return every stored liquidity record, sorted by ticker."""
        statement = select(V2Liquidity).order_by(V2Liquidity.symbol_code)
        return [_liquidity_record(row) for row in self._session.scalars(statement)]

    def list_market_cap(self) -> list[MarketCapRecord]:
        """Return every stored market-cap record, sorted by ticker."""
        statement = select(V2MarketCap).order_by(V2MarketCap.symbol_code)
        return [_market_cap_record(row) for row in self._session.scalars(statement)]

    def price_adjustment_bases(self) -> dict[str, str]:
        """Return the distinct price-adjustment basis (or bases) per ticker."""
        statement = select(
            V2DailyPrice.symbol_code, V2DailyPrice.price_adjustment_basis
        ).distinct()
        grouped: dict[str, set[str]] = {}
        for symbol, basis in self._session.execute(statement):
            grouped.setdefault(symbol.upper(), set()).add(basis)
        return {symbol: "+".join(sorted(bases)) for symbol, bases in grouped.items()}

    def overall_latest_price_date(self) -> date | None:
        """Return the newest stored bar date across every ticker (or ``None``)."""
        return self._session.scalar(select(func.max(V2DailyPrice.date)))

    def history_starts(self) -> dict[str, date]:
        """Return the first stored bar date per ticker (one cheap group-by).

        Used to surface a "partial history" warning without a query per ticker.
        """
        statement = select(V2DailyPrice.symbol_code, func.min(V2DailyPrice.date)).group_by(
            V2DailyPrice.symbol_code
        )
        return {symbol.upper(): start for symbol, start in self._session.execute(statement)}

    # -- adjustment-quality flags -----------------------------------------
    def upsert_adjustment_flags(self, records: Sequence[AdjustmentFlagRecord]) -> int:
        """Upsert the per-ticker adjustment-quality flags computed by the job."""
        rows = [
            {
                "ticker": record.ticker.strip().upper(),
                "severity": record.severity,
                "flagged": record.flagged,
                "exclude_from_group_indices": record.exclude_from_group_indices,
                "reasons": list(record.reasons),
                "dates": [day.isoformat() for day in record.dates],
                "anomalies": [
                    {
                        "date": anomaly.date.isoformat(),
                        "exclude": anomaly.exclude,
                        "category": anomaly.category,
                        "reason": anomaly.reason,
                    }
                    for anomaly in record.anomalies
                ],
                "source": record.source,
                "data_as_of": record.data_as_of,
            }
            for record in records
        ]
        return _bulk_upsert(
            self._session,
            V2AdjustmentFlag,
            rows,
            key_columns=["ticker"],
            update_columns=[
                "severity",
                "flagged",
                "exclude_from_group_indices",
                "reasons",
                "dates",
                "anomalies",
                "source",
                "data_as_of",
            ],
        )

    def list_adjustment_flags(self) -> list[AdjustmentFlagRecord]:
        """Return every stored adjustment-quality flag, sorted by ticker."""
        statement = select(V2AdjustmentFlag).order_by(V2AdjustmentFlag.ticker)
        return [_adjustment_flag_record(row) for row in self._session.scalars(statement)]

    def adjustment_flags_available(self) -> bool:
        """Return ``True`` when the flags were computed (the table is not empty)."""
        count = self._session.scalar(select(func.count()).select_from(V2AdjustmentFlag))
        return bool(count)


    # -- financial ratios (V2b) -------------------------------------------
    def upsert_ratios(self, records: Sequence[RatioRecord]) -> int:
        """Upsert per-ticker, per-period trimmed ratios."""
        rows = [
            {
                "symbol_code": record.symbol.upper(),
                "period": record.period,
                "period_type": record.period_type,
                "ratio_group": record.ratio_group,
                "ratios": dict(record.ratios),
                "source": record.source,
                "data_as_of": record.data_as_of,
            }
            for record in records
        ]
        return _bulk_upsert(
            self._session,
            V2FinancialRatio,
            rows,
            key_columns=["symbol_code", "period", "period_type"],
            update_columns=["ratio_group", "ratios", "source", "data_as_of"],
        )

    def get_ratios(self, symbol: str) -> list[RatioRecord]:
        """Return one ticker's stored ratios, newest period first."""
        statement = (
            select(V2FinancialRatio)
            .where(V2FinancialRatio.symbol_code == symbol.upper())
            .order_by(V2FinancialRatio.period.desc(), V2FinancialRatio.period_type)
        )
        return [_ratio_record(row) for row in self._session.scalars(statement)]

    def get_ratio(
        self, symbol: str, period: date, period_type: str
    ) -> RatioRecord | None:
        """Return one ticker's ratio record for ``(period, period_type)``, or ``None``."""
        row = self._session.get(V2FinancialRatio, (symbol.upper(), period, period_type))
        return _ratio_record(row) if row is not None else None

    def list_ratios(
        self, *, period: date | None = None, period_type: str | None = None
    ) -> list[RatioRecord]:
        """Return stored ratios, optionally filtered to one period and period type."""
        statement = select(V2FinancialRatio)
        if period is not None:
            statement = statement.where(V2FinancialRatio.period == period)
        if period_type is not None:
            statement = statement.where(V2FinancialRatio.period_type == period_type)
        statement = statement.order_by(
            V2FinancialRatio.symbol_code, V2FinancialRatio.period
        )
        return [_ratio_record(row) for row in self._session.scalars(statement)]

    def latest_ratio_period(self, symbol: str) -> date | None:
        """Return the newest stored ratio period for ``symbol`` (or ``None``)."""
        return self._session.scalar(
            select(func.max(V2FinancialRatio.period)).where(
                V2FinancialRatio.symbol_code == symbol.upper()
            )
        )

    # -- precomputed sector statistics (V2b) ------------------------------
    def upsert_sector_statistics(
        self, records: Sequence[SectorStatisticRecord]
    ) -> int:
        """Upsert the precomputed sector peer statistics."""
        rows = [
            {
                "sector": record.sector,
                "ratio": record.ratio,
                "period": record.period,
                "period_type": record.period_type,
                "n": record.n,
                "median": record.median,
                "mean": record.mean,
                "winsorized_mean": record.winsorized_mean,
                "p5": record.p5,
                "p95": record.p95,
                "minimum": record.minimum,
                "maximum": record.maximum,
                "percentile_ranks": dict(record.percentile_ranks),
                "source": record.source,
                "data_as_of": record.data_as_of,
            }
            for record in records
        ]
        return _bulk_upsert(
            self._session,
            V2SectorStatistic,
            rows,
            key_columns=["sector", "ratio", "period", "period_type"],
            update_columns=[
                "n", "median", "mean", "winsorized_mean", "p5", "p95",
                "minimum", "maximum", "percentile_ranks", "source", "data_as_of",
            ],
        )

    def list_sector_statistics(self) -> list[SectorStatisticRecord]:
        """Return every stored sector statistic, sorted by sector/ratio/period."""
        statement = select(V2SectorStatistic).order_by(
            V2SectorStatistic.sector,
            V2SectorStatistic.ratio,
            V2SectorStatistic.period,
            V2SectorStatistic.period_type,
        )
        return [
            _sector_statistic_record(row) for row in self._session.scalars(statement)
        ]


__all__ = ["V2Store"]

