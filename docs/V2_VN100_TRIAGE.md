# VN100 backfill triage (data quality)

- Triaged: 2026-11-23 against the stored `vnopt.db` (the completed VN100 backfill).
- Scope: **100 VN100 members**, 93,254 bars (`2023-01-03`..`2026-11-20`,
  `source=ssi_statistics`, `basis=ssi_adjusted`), 492 corporate actions.
- No price or schema change; the policy that came out of this triage is
  `docs/DECISIONS.md` D-017.

The investigation used only the stored data and the recorded fixtures. KBS raw
bars are **not** stored for the tickers below (the V1 `prices_daily` table only has
DCM/LPB/VHM, and the KBS/VCI fixtures are VCB-only), so the "which series glitches"
questions were answered by adjusted-vs-raw internal consistency.

## 1. Findings by type and ticker

Before the policy change, `run_v2_quality_checks` over the 100 members produced
**97 error findings + 4 warnings** (an independent recomputation; the original run
report said 94, a counting-precedent difference of 3 that does not change any
conclusion):

| check | severity | count |
|---|---|---|
| `adjusted_vs_raw_mismatch` | error | 90 (42 reconciliation difference + 48 ratio changed) |
| `missing_trading_days` | error | 6 |
| `suspicious_returns` | error | 1 |
| `adjusted_vs_raw_mismatch` | warning (HPG) | 3 |
| `missing_trading_days` | warning (BSR halt) | 1 |

Ratio-changed findings were concentrated in 5 tickers: GEE 20, VTP 12, TAL 9,
MCH 4, NAB 3. Missing days: GEE 33, TAL 11, VTP 7, NAB 6, MCH 5, SIP 5.

## 2. Reconciliation differences at ISS ex-dates

| ticker | ex-date | ratio | raw gap | adj gap | removed | model expects | verdict |
|---|---|---|---|---|---|---|---|
| NVL | 2026-09-30 | 0.3333 | −0.97% | −0.24% | −0.73% | −25.0% | **model too simple** (rights issue) |
| VIX | 2024-07-31 | 0.95+0.1+0.1 | −14.77% | +6.55% | −21.32% | −57.6% | **model too simple** (rights issue) |
| HCM | 2024-01-02 | 0.5+0.15 | −27.78% | +3.96% | −31.74% | −42.0% | **model too simple** (rights/bonus mix) |
| EVF | 2023-09-21 | 1.0 | +0.81% | +6.84% | −6.04% | −50.0% | **adjustment looks wrong** (spurious gain) |

The stored action fields are `event_type` + `exright_date` + `ratio` + `value`;
`value` is `0.0` for every ISS (SSI does not publish a subscription price). The
`-ratio/(1+ratio)` model is the **bonus-share** model; a rights issue's ex-rights
gap also depends on the subscription price, so the model overstates the gap and the
three genuine rights issues look like differences. EVF is the opposite: the raw
close barely moved (+0.81%) while the adjusted close jumped **+6.84%** on the
ex-date (and partly reversed two sessions later), i.e. the adjustment injected a
spurious gain.

Policy: any ISS ex-date is `unsupported`; only an all-DIV event is verified; an ISS
ex-date whose adjusted close rises >5% on a flat raw close (|gap|<2%) is
`adjustment_suspect`.

## 3. "Ratio changed … no corporate action" (GEE, MCH, NAB, TAL, VTP)

The glitch series varies; GEE is the clear return-corrupting case.

| ticker | flags | glitch series | annualized vol all → cleaned |
|---|---|---|---|
| **GEE** | 20 | **SSI adjusted close** — spurious 7–11% one-day drops that reverse (e.g. −8.8%/+11.2%, −9.5%/+7.2%, −9.7%/+7.0%) | 54.7% → 52.1% (−4.7%) |
| TAL | 9 | large raw moves the feed omits + adjusted reversals | 38.7% → 37.8% (−2.5%) |
| VTP | 12 | mostly raw-side noise; adjusted mostly smooth | 39.7% → 39.3% (−1.0%) |
| NAB | 3 | real actions the feed omits | 25.6% → 25.5% (−0.6%) |
| MCH | 4 | mild adjusted-vs-raw daily drift (VGI/OIL class) | 30.6% → 30.5% (−0.2%) |

"Cleaned" removes the return into each flagged day and the return out of it.

## 4. Missing trading days

All gaps are **interior** (bars before and after), so they are ticker-specific
**halts/suspensions or late-listing gaps**, not exchange holidays (the VN-Index
calendar already removes holidays): GEE (early-2023 singles + 2024-07-19..26),
TAL (late listing 2024-01-09 + 2024-09/10 and 2025-07 halts), VTP (2024-03-01..11),
NAB (2024-02-29..03-07), MCH (2025-12-18..24), SIP (2023-08-01..07).

Because a halt has no bar, the analytics engine must not turn the first bar after it
into a multi-day return: `calendar_returns` now emits a return only when the ticker
has bars on both the day and the preceding benchmark trading day, and the group
index drops the missing-bar days (renormalising weights).

## 5. TAL +15.9% on 2025-04-10

A **single-day** move: 2025-04-09 and 2025-04-10 are consecutive and the adjusted
and raw closes moved identically (+15.93% both; the adj/raw ratio is unchanged). It
is not an adjustment error, but +15.93% exceeds even the 15% UPCoM band and is
impossible under TAL's HOSE 7% band, so the bar is suspect (a listing-transfer/limit
exception or bad data). TAL also has 9 ratio glitches and 11 missing days, so it is
excluded by default.

## 6. VN100 members with no prices

In the stored DB **all 100 members have bars**; zero have literally no prices. The
four members with no prices for most of the window are the 2025 listings —
**VPL** (2025-05-13), **TCX** (2025-10-21), **VPX** (2025-12-11), **VCK**
(2025-12-16) — because they IPO'd/transferred to HOSE in 2025. (DSE 2024-07-01 and
TAL 2024-01-09 are also later listings.) They satisfy the 80%-coverage rule only
over the recent window and are handled by the existing coverage exclusion.

## 7. Severity policy and default exclusion

Only integrity findings fail the step (`no_data`, `duplicate_dates`, stale latest
bar, empty benchmark calendar, schema). Per-ticker findings are warnings stored as
flags. The group indices drop, by default, only tickers whose flag is
return-corrupting (reversing move, >15% move, reconciliation difference/suspect).

On the current data that is **5 names — CII, EVF, GEE, NVL, TAL** — while
**HPG, MCH, NAB, VTP** are flagged but stay included (warnings only). The
`EXPLAINED_FINDINGS` config is kept and extended with the documented glitch and
halt cases.
