"""Built-in reference data used as the last-resort fallback.

Ticker search and the VN30 preset must keep working when every anonymous
provider is unreachable (offline development, a restricted corporate/cloud
network, or a cold serverless instance). This module holds a deliberately small
snapshot of liquid Vietnamese stocks plus the VN30 membership recorded from KBS's
public group endpoint.

Assumptions and limits:

* The snapshot is **not** maintained in real time and must never override live
  data. :meth:`data.sync.SyncService.sync_reference_data` consults it only after
  the whole failover chain failed and the relevant table is still empty.
* Only stock symbols are seeded, and only VN30 has seed constituents - a partial
  HOSE/HNX/UPCoM list cannot honestly claim to be an index constituency.
* Rows written from here carry :data:`SEED_SOURCE` as their ``source`` so callers
  can tell seeded metadata from a provider's listing.
"""

from __future__ import annotations

from data.models import SymbolInfo

#: ``source`` stored on every row written from the built-in snapshot.
SEED_SOURCE = "seed"

#: Liquid stock codes per exchange, recorded once and kept intentionally short.
SEED_SYMBOLS: dict[str, tuple[str, ...]] = {
    "HOSE": (
        "ACB",
        "ANV",
        "BCM",
        "BID",
        "BSR",
        "BVH",
        "CTD",
        "CTG",
        "DCM",
        "DGC",
        "DIG",
        "DPM",
        "DXG",
        "EIB",
        "FPT",
        "FRT",
        "GAS",
        "GEX",
        "GMD",
        "GVR",
        "HDB",
        "HPG",
        "KBC",
        "KDH",
        "LPB",
        "MBB",
        "MCH",
        "MSN",
        "MWG",
        "NVL",
        "PDR",
        "PLX",
        "PNJ",
        "POW",
        "PVD",
        "PVT",
        "REE",
        "SAB",
        "SBT",
        "SHB",
        "SSB",
        "SSI",
        "STB",
        "TCB",
        "TCH",
        "TCX",
        "TPB",
        "VCB",
        "VCG",
        "VHM",
        "VIB",
        "VIC",
        "VJC",
        "VNM",
        "VND",
        "VPB",
        "VPI",
        "VPL",
        "VRE",
        "VSC",
    ),
    "HNX": (
        "BVS",
        "CEO",
        "HUT",
        "IDC",
        "L14",
        "L18",
        "LAS",
        "MBS",
        "NTP",
        "PLC",
        "PVB",
        "PVC",
        "PVS",
        "SHS",
        "SLS",
        "TIG",
        "TNG",
        "TVD",
        "VC3",
        "VCS",
        "VFS",
        "VGP",
    ),
    "UPCOM": (
        "ABB",
        "ACV",
        "MSR",
        "PGB",
        "QNS",
        "SGB",
        "VEA",
        "VGT",
    ),
}

#: Index code -> member codes for indices the snapshot covers (VN30 only).
SEED_INDEX_CONSTITUENTS: dict[str, tuple[str, ...]] = {
    "VN30": (
        "ACB",
        "BID",
        "BSR",
        "CTG",
        "FPT",
        "GAS",
        "GVR",
        "HDB",
        "HPG",
        "LPB",
        "MBB",
        "MCH",
        "MSN",
        "MWG",
        "SAB",
        "SHB",
        "SSB",
        "SSI",
        "STB",
        "TCB",
        "TCX",
        "VCB",
        "VHM",
        "VIB",
        "VIC",
        "VJC",
        "VNM",
        "VPB",
        "VPL",
        "VRE",
    ),
}


def seed_symbols(exchange: str | None = None) -> list[SymbolInfo]:
    """Return the built-in stock snapshot, optionally limited to one exchange.

    ``exchange`` is matched case-insensitively (``"UPCoM"`` and ``"UPCOM"`` both
    select the UPCoM bucket). Names are omitted because the snapshot stores codes
    only; a live provider replaces these rows on the next successful listing.
    """
    wanted = exchange.strip().upper() if exchange else None
    return [
        SymbolInfo(code=code, exchange=board, type="stock", source=SEED_SOURCE)
        for board, codes in SEED_SYMBOLS.items()
        if wanted is None or board == wanted
        for code in codes
    ]


def seed_constituents(index_code: str) -> list[str]:
    """Return the built-in members of ``index_code`` (empty when not covered)."""
    return list(SEED_INDEX_CONSTITUENTS.get(index_code.strip().upper(), ()))
