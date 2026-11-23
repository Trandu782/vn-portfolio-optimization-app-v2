"""Merge the SSI symbol master with the KBS tradable-stock list.

The SSI iBoard ``stock-info`` bulk endpoint provides ticker -> exchange (and a
company name) for every listed security; KBS ``/stock/search/data`` provides the
authoritative list of tradable stocks. The merged master keeps every KBS stock and
prefers SSI's exchange/name where it has them, so a consumer gets one record per
tradable stock with the best available metadata. No field is invented: a ticker
missing from both sides never appears, and a missing exchange stays an empty
string rather than a guess.

This mirrors :func:`data.v2.static_sector.kbs_symbol_exchanges`; both read the
same KBS ``SymbolInfo`` model without touching V1 behaviour.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from data.models import SymbolInfo
from data.v2.schemas import SymbolMaster

#: Source tag stamped on every merged record (both providers contributed).
MERGED_SOURCE = "ssi_statistics+kbs"


def merge_symbol_master(
    ssi: Sequence[SymbolMaster],
    kbs: Iterable[SymbolInfo],
) -> list[SymbolMaster]:
    """Merge SSI's exchange master with KBS's tradable-stock list.

    Args:
        ssi: SSI symbol-master rows (``data`` from ``stock-info``).
        kbs: KBS symbols (``data.models.SymbolInfo``); the authoritative stock list.

    Returns:
        One :class:`SymbolMaster` per ticker found on either side, sorted by
        ticker. SSI's ``exchange``/``name`` win when present; otherwise KBS fills
        them. Every record's ``source`` is :data:`MERGED_SOURCE`.
    """
    ssi_by_ticker: dict[str, SymbolMaster] = {}
    for row in ssi:
        code = row.ticker.strip().upper()
        if code and code not in ssi_by_ticker:
            ssi_by_ticker[code] = row

    merged: dict[str, SymbolMaster] = {}
    for info in kbs:
        code = info.code.strip().upper()
        if not code:
            continue
        ssi_row = ssi_by_ticker.get(code)
        exchange = (ssi_row.exchange if ssi_row and ssi_row.exchange else info.exchange) or ""
        name = (ssi_row.name if ssi_row and ssi_row.name else info.name) or None
        merged[code] = SymbolMaster(
            ticker=code,
            exchange=exchange.strip().upper(),
            name=name,
            security_type=info.type or (ssi_row.security_type if ssi_row else None),
            source=MERGED_SOURCE,
        )

    # SSI tickers absent from KBS are still real securities; keep them so nothing
    # is silently dropped, marked with the merged source.
    for code, ssi_row in ssi_by_ticker.items():
        merged.setdefault(
            code,
            SymbolMaster(
                ticker=code,
                exchange=ssi_row.exchange,
                name=ssi_row.name,
                security_type=ssi_row.security_type,
                source=MERGED_SOURCE,
            ),
        )
    return [merged[code] for code in sorted(merged)]


__all__ = ["MERGED_SOURCE", "merge_symbol_master"]
