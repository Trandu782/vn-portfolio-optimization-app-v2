/**
 * Pure helpers behind the Sector Analysis UI (docs/V2_SPEC.md section 3.2).
 *
 * The React components stay thin: sorting, row classification, the clustered heatmap
 * order, the legend toggle, the excluded-tickers summary and the view-state decision
 * live here so they are unit-tested with the Node test runner (this repo has no DOM
 * render harness).
 */

import type {
  SectorAnalytics,
  SectorCorrelation,
  SectorDefaultExcluded,
  SectorGroupAnalytics,
} from "./api";

export type SectorSortKey =
  | "name"
  | "period_return"
  | "excess_return"
  | "beta"
  | "r_squared"
  | "annualized_volatility"
  | "constituent_count";

export type SortDirection = "asc" | "desc";

/** One row of the Sector Beta & Performance table. */
export interface SectorRow {
  name: string;
  periodReturn: number | null;
  excessReturn: number | null;
  beta: number | null;
  rSquared: number | null;
  volatility: number | null;
  constituentCount: number;
  defaultExcludedCount: number;
  status: "ok" | "insufficient";
  lowReliability: boolean;
  /** True when the engine reported that the single-stock cap could not be applied. */
  capOff: boolean;
  /** The engine's exact "cap off" warning text, for a tooltip (null when capped). */
  capOffReason: string | null;
}

/** The engine reports an infeasible single-stock cap with this warning prefix. */
const CAP_OFF_PREFIX = "single-stock cap";

/** Return the engine's cap-not-applied warning for a group, or null. */
export function capOffWarning(warnings: readonly string[] | undefined): string | null {
  return (warnings ?? []).find((warning) => warning.startsWith(CAP_OFF_PREFIX)) ?? null;
}

/** Map one analytics group to a table row (with the engine's cap-off warning). */
export function toSectorRow(group: SectorGroupAnalytics): SectorRow {
  const { metrics, index } = group;
  const capReason = capOffWarning(index.warnings);
  return {
    name: index.group,
    periodReturn: metrics.period_return ?? null,
    excessReturn: metrics.excess_return ?? null,
    beta: metrics.beta ?? null,
    rSquared: metrics.r_squared ?? null,
    volatility: metrics.annualized_volatility ?? null,
    constituentCount: index.constituent_count,
    defaultExcludedCount: group.default_excluded_count ?? 0,
    status: index.status,
    lowReliability: metrics.low_reliability,
    capOff: capReason !== null,
    capOffReason: capReason,
  };
}

/** A row badge: "Too few stocks" for greyed sectors, "Low reliability" for short windows. */
export interface RowBadge {
  label: string;
  tone: "muted" | "warning";
}

/**
 * Badge for one table row. A sector too thin to publish (< 3 constituents) is about
 * the group size, not the observation count, so it says "Too few stocks (needs 3)";
 * "Low reliability" is reserved for published sectors with < 60 observations.
 */
export function rowBadge(row: SectorRow): RowBadge | null {
  if (row.status === "insufficient") {
    return { label: "Too few stocks (needs 3)", tone: "muted" };
  }
  if (row.lowReliability) {
    return { label: "Low reliability", tone: "warning" };
  }
  return null;
}

/** True when a row can be sent to the Optimizer (a published index only). */
export function isRowSelectable(row: SectorRow): boolean {
  return row.status === "ok";
}

/** True when a row should be greyed out (too thin to publish an index). */
export function isRowGreyed(row: SectorRow): boolean {
  return row.status === "insufficient";
}

const SORT_KEYS: Record<SectorSortKey, (row: SectorRow) => number | string | null> = {
  name: (row) => row.name,
  period_return: (row) => row.periodReturn,
  excess_return: (row) => row.excessReturn,
  beta: (row) => row.beta,
  r_squared: (row) => row.rSquared,
  annualized_volatility: (row) => row.volatility,
  constituent_count: (row) => row.constituentCount,
};

/**
 * Sort rows for the table. Insufficient rows always sort last (they are greyed and
 * informational); null numeric values sort last within each status group.
 */
export function sortSectorRows(
  rows: readonly SectorRow[],
  key: SectorSortKey,
  direction: SortDirection,
): SectorRow[] {
  const getter = SORT_KEYS[key];
  const factor = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (a.status !== b.status) {
      return a.status === "ok" ? -1 : 1;
    }
    const av = getter(a);
    const bv = getter(b);
    if (av === null && bv === null) return a.name.localeCompare(b.name);
    if (av === null) return 1;
    if (bv === null) return -1;
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv)) * factor;
    }
    return (Number(av) - Number(bv)) * factor;
  });
}

/** Toggle one legend entry, returning a new hidden map. */
export function toggleHidden(
  hidden: Readonly<Record<string, boolean>>,
  id: string,
): Record<string, boolean> {
  return { ...hidden, [id]: !hidden[id] };
}

/** Hide every sector line while keeping the benchmark line visible. */
export function hideAllSectors(sectorIds: readonly string[]): Record<string, boolean> {
  const next: Record<string, boolean> = { benchmark: false };
  for (const id of sectorIds) {
    next[id] = true;
  }
  return next;
}

/** Summarize whether all chart lines are visible or only the benchmark is visible. */
export function relativeChartVisibility(
  hidden: Readonly<Record<string, boolean>>,
  sectorIds: readonly string[],
): { allVisible: boolean; onlyBenchmarkVisible: boolean } {
  const benchmarkHidden = hidden.benchmark ?? false;
  const allSectorsHidden = sectorIds.every((id) => hidden[id] === true);
  const anySectorHidden = sectorIds.some((id) => hidden[id] === true);
  const allVisible = !benchmarkHidden && !anySectorHidden;
  const onlyBenchmarkVisible =
    sectorIds.length === 0 || (!benchmarkHidden && allSectorsHidden);
  return { allVisible, onlyBenchmarkVisible };
}

/** True when every pair is mirrored and the diagonal is 1 within `tolerance`. */
export function isCorrelationMatrixValid(
  matrix: readonly (readonly number[])[],
  tolerance = 1e-9,
): boolean {
  const size = matrix.length;
  for (let row = 0; row < size; row += 1) {
    if (Math.abs((matrix[row][row] ?? Number.NaN) - 1) > tolerance) return false;
    for (let column = row + 1; column < size; column += 1) {
      if (Math.abs((matrix[row][column] ?? 0) - (matrix[column][row] ?? 0)) > tolerance) {
        return false;
      }
    }
  }
  return true;
}

/** Reorder the correlation matrix into the clustered (dendrogram) order. */
export function orderedHeatmap(correlation: SectorCorrelation): {
  labels: string[];
  matrix: number[][];
} {
  const labels = correlation.labels ?? [];
  const matrix = correlation.matrix ?? [];
  const ordered = correlation.ordered_labels ?? labels;
  const position = new Map(labels.map((label, index) => [label, index]));
  const found = ordered
    .map((label) => position.get(label))
    .filter((index): index is number => index !== undefined);
  const order = found.length === labels.length ? found : labels.map((_, index) => index);
  return {
    labels: order.map((index) => labels[index]),
    matrix: order.map((row) => order.map((column) => matrix[row]?.[column] ?? 0)),
  };
}

/** One sector's default-excluded tickers. */
export interface ExcludedSectorGroup {
  sector: string;
  tickers: SectorDefaultExcluded[];
}

/** Group the default-excluded tickers by sector, largest group first. */
export function summarizeExcluded(items: readonly SectorDefaultExcluded[]): ExcludedSectorGroup[] {
  const bySector = new Map<string, SectorDefaultExcluded[]>();
  for (const item of items) {
    const sector = item.sector ?? "Unknown";
    const list = bySector.get(sector) ?? [];
    list.push(item);
    bySector.set(sector, list);
  }
  return [...bySector.entries()]
    .map(([sector, tickers]) => ({ sector, tickers }))
    .sort((a, b) => b.tickers.length - a.tickers.length || a.sector.localeCompare(b.sector));
}

/** One plain-language summary row in the excluded-tickers panel. */
export interface ExcludedTickerView {
  ticker: string;
  sector: string;
  category: "data_glitch" | "thin_trading";
  categoryLabel: string;
  /** Main reason plus the number of affected dates (one line). */
  summary: string;
  /** The anomaly dates inside the window (ISO strings). */
  affectedDates: string[];
  /** The full plain-language list, for the expandable details section. */
  details: string[];
}

/** Map a stored excluded ticker to its panel view (plain language, no jargon). */
export function toExcludedView(item: SectorDefaultExcluded): ExcludedTickerView {
  const category = item.category === "thin_trading" ? "thin_trading" : "data_glitch";
  const categoryLabel = category === "thin_trading" ? "Thin trading" : "Data glitch";
  const affectedDates = (item.affected_dates ?? []).map((value) => String(value));
  const details = (item.reasons ?? []).filter((line) => line.trim().length > 0);
  const reason = (item.reason ?? "").trim() || details[0] || "adjustment-quality issue";
  const mainReason = reason.charAt(0).toUpperCase() + reason.slice(1);
  const count = affectedDates.length;
  const summary =
    count > 0
      ? `${mainReason} — ${count} affected date${count === 1 ? "" : "s"}`
      : mainReason;
  return {
    ticker: item.ticker,
    sector: item.sector ?? "Unknown",
    category,
    categoryLabel,
    summary,
    affectedDates,
    details,
  };
}

/** The fixed sector palette; the line chart and the scatter share it by name. */
export const SECTOR_COLORS = [
  "#2563eb", "#16a34a", "#ea580c", "#7c3aed", "#0891b2", "#ca8a04",
  "#dc2626", "#4f46e5", "#059669", "#db2777", "#65a30d", "#0284c7",
] as const;

/** The colour for a sector at position ``index`` (wraps around the palette). */
export function sectorColor(index: number): string {
  return SECTOR_COLORS[index % SECTOR_COLORS.length];
}

const BENCHMARK_LABELS: Record<string, string> = {
  VNINDEX: "VN-Index",
  VN30: "VN30",
  VN100: "VN100",
};

/** Display name for a benchmark code (``VNINDEX`` -> ``VN-Index``). */
export function benchmarkLabel(code: string): string {
  return BENCHMARK_LABELS[code.trim().toUpperCase()] ?? code;
}

// Correlation colour endpoints: a neutral grey at 0 (visible on a dark background),
// red at +1 and blue at -1. The scale stays -1..+1; only the neutral stop is opaque.
const CORRELATION_NEUTRAL: readonly [number, number, number] = [107, 114, 128];
const CORRELATION_POSITIVE: readonly [number, number, number] = [220, 38, 38];
const CORRELATION_NEGATIVE: readonly [number, number, number] = [37, 99, 235];

function mixChannel(from: number, to: number, strength: number): number {
  return Math.round(from + (to - from) * strength);
}

/**
 * Opaque colour for a correlation in [-1, 1]. Unlike the old alpha ramp, 0 is a visible
 * neutral grey instead of transparent, so cells read on the app's dark background, and
 * the -1..+1 scale (blue -> grey -> red) is unchanged.
 */
export function correlationColor(value: number): string {
  const clamped = Math.max(-1, Math.min(1, Number.isFinite(value) ? value : 0));
  const target = clamped >= 0 ? CORRELATION_POSITIVE : CORRELATION_NEGATIVE;
  const strength = Math.abs(clamped);
  const r = mixChannel(CORRELATION_NEUTRAL[0], target[0], strength);
  const g = mixChannel(CORRELATION_NEUTRAL[1], target[1], strength);
  const b = mixChannel(CORRELATION_NEUTRAL[2], target[2], strength);
  return `rgb(${r}, ${g}, ${b})`;
}

export type AnalyticsViewState = "loading" | "ready" | "empty" | "unavailable" | "error";

/** Decide which state the Sector tab renders from the fetch outcome. */
export function analyticsViewState(
  loading: boolean,
  error: string | null,
  groupCount: number,
): AnalyticsViewState {
  if (loading) return "loading";
  if (error !== null) {
    return /no stored|V2 data|no data/i.test(error) ? "unavailable" : "error";
  }
  return groupCount === 0 ? "empty" : "ready";
}

/** True when the payload has at least one published sector. */
export function hasPublishedSector(payload: SectorAnalytics | null): boolean {
  return (payload?.groups ?? []).some((group) => group.index.status === "ok");
}

/** Names of sectors that can be selected and sent to the Optimizer. */
export function selectableSectorNames(rows: readonly SectorRow[]): string[] {
  return rows.filter(isRowSelectable).map((row) => row.name);
}

/** Summary of how many selectable sectors are currently checked. */
export function sectorSelectionSummary(
  rows: readonly SectorRow[],
  selected: ReadonlySet<string>,
): {
  selectableCount: number;
  selectedCount: number;
  allSelected: boolean;
  someSelected: boolean;
} {
  const selectable = selectableSectorNames(rows);
  const selectableCount = selectable.length;
  const selectedCount = selectable.filter((name) => selected.has(name)).length;
  const allSelected = selectableCount > 0 && selectedCount === selectableCount;
  const someSelected = selectedCount > 0 && selectedCount < selectableCount;
  return { selectableCount, selectedCount, allSelected, someSelected };
}

/** Toggle all selectable sectors: clears when all are selected, otherwise selects all. */
export function toggleAllSelectableSectors(
  rows: readonly SectorRow[],
  selected: ReadonlySet<string>,
): Set<string> {
  const { allSelected } = sectorSelectionSummary(rows, selected);
  return allSelected ? new Set() : new Set(selectableSectorNames(rows));
}
