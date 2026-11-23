/**
 * Pure helpers behind the Sector Analysis | Fundamentals sub-tab (docs/V2_SPEC.md
 * section 3.3).
 *
 * The React components stay thin: group labels, category grouping, the
 * direction-aware better/similar/worse verdict, the "n/m" and "insufficient peers"
 * rules, the box-plot summary and the view-state decision live here so they are
 * unit-tested with the Node test runner (this repo has no DOM render harness).
 *
 * The API publishes every label, category and unit, so the UI renders what the
 * backend returns instead of hardcoding the registry.
 */

import type {
  FundamentalsComparison,
  FundamentalsPeerStatistic,
  FundamentalsRatio,
} from "./api";

/** A peer set below this count is too small to rank against; warn instead. */
export const MIN_PEERS = 5;

/** Values within this relative distance of the sector median are "similar". */
export const SIMILAR_TOLERANCE = 0.1;

/** The exact wording the spec asks for when N < 5. */
export const INSUFFICIENT_PEERS_LABEL = "insufficient peers (N < 5)";

/** How a ratio compares with its sector median (direction-aware). */
export type RatioVerdict =
  | "better"
  | "similar"
  | "worse"
  | "neutral"
  | "not_meaningful"
  | "insufficient_peers";

const GROUP_LABELS: Record<string, string> = {
  banks: "Banks",
  securities: "Financial services",
  insurance: "Insurance",
  general: "General companies",
};

/**
 * Display label for a peer group.
 *
 * ``Financial Services`` is shown as "Financial services" (not "Securities")
 * because the group also covers consumer-finance names such as EVF, and every
 * other sector is a "General companies" peer. An unknown group falls back to the
 * general label rather than leaking a raw key into the UI.
 */
export function groupLabel(ratioGroup: string | null | undefined): string {
  if (!ratioGroup) return GROUP_LABELS.general;
  return GROUP_LABELS[ratioGroup] ?? GROUP_LABELS.general;
}

/**
 * Format one ratio value. Percentages are stored on a 0-100 scale ("17.3" is
 * 17.3%), so they render with a ``%`` sign and one decimal; multiples use two.
 * A missing value renders as "n/m".
 */
export function formatRatioValue(
  value: number | null | undefined,
  isPercentage: boolean,
  digits = 1,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "n/m";
  }
  return isPercentage ? `${value.toFixed(digits)}%` : value.toFixed(2);
}

/** Format a ratio's own value, honouring the backend's "not meaningful" flag. */
export function ratioDisplayValue(ratio: FundamentalsRatio): string {
  if (ratio.not_meaningful) return "n/m";
  return formatRatioValue(ratio.value, ratio.is_percentage);
}

/** Format a percentile rank (0-100) as a whole percentage, or "n/m" when absent. */
export function formatPercentileRank(rank: number | null | undefined): string {
  if (rank === null || rank === undefined || !Number.isFinite(rank)) return "n/m";
  return `${Math.round(rank)}%`;
}

/**
 * Classify a ratio against its sector median.
 *
 * Rules (docs/V2_SPEC.md section 6):
 * - a missing value or a valuation multiple flagged "n/m" is ``not_meaningful``;
 * - a peer set with fewer than :data:`MIN_PEERS` values is ``insufficient_peers``;
 * - valuation multiples (``direction === "neutral"``) are always ``neutral``;
 * - within :data:`SIMILAR_TOLERANCE` of the median is ``similar``;
 * - otherwise ``better``/``worse`` depending on whether higher or lower is better.
 */
export function classifyRatio(ratio: FundamentalsRatio): RatioVerdict {
  if (ratio.not_meaningful || ratio.value === null || ratio.value === undefined) {
    return "not_meaningful";
  }
  const peers = ratio.peers;
  if (!peers || peers.n < MIN_PEERS) {
    return "insufficient_peers";
  }
  const median = peers.median ?? null;
  if (median === null) {
    return "not_meaningful";
  }
  if (ratio.direction === "neutral") {
    return "neutral";
  }
  const scale = Math.abs(median);
  const relative = scale === 0 ? Math.abs(ratio.value) : Math.abs(ratio.value - median) / scale;
  if (relative <= SIMILAR_TOLERANCE) {
    return "similar";
  }
  const higher = ratio.value > median;
  const improved = ratio.direction === "higher" ? higher : !higher;
  return improved ? "better" : "worse";
}

/** Plain-language label for a verdict (used by chips and tooltips). */
export function verdictLabel(verdict: RatioVerdict): string {
  switch (verdict) {
    case "better":
      return "Better than sector";
    case "similar":
      return "Similar to sector";
    case "worse":
      return "Worse than sector";
    case "neutral":
      return "Valuation (neutral)";
    case "insufficient_peers":
      return INSUFFICIENT_PEERS_LABEL;
    default:
      return "n/m";
  }
}

/** Coarse colour tone for a verdict, shared by the cards, table and box plot. */
export type VerdictTone = "good" | "bad" | "warn" | "neutral";

/** Map a verdict to its colour tone (better=good, worse=bad, similar=warn). */
export function verdictTone(verdict: RatioVerdict): VerdictTone {
  switch (verdict) {
    case "better":
      return "good";
    case "worse":
      return "bad";
    case "similar":
      return "warn";
    default:
      return "neutral";
  }
}

/** Tailwind text colour per tone (literal classes so Tailwind keeps them). */
export const TONE_TEXT_CLASS: Record<VerdictTone, string> = {
  good: "text-emerald-700 dark:text-emerald-400",
  bad: "text-red-700 dark:text-red-400",
  warn: "text-amber-700 dark:text-amber-400",
  neutral: "text-gray-700 dark:text-gray-300",
};

/** Tailwind chip colours per tone (literal classes so Tailwind keeps them). */
export const TONE_CHIP_CLASS: Record<VerdictTone, string> = {
  good: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  bad: "bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200",
  warn: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  neutral: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
};

/** One category's ratios, in the API's ratio-set order. */
export interface RatioCategoryGroup {
  category: string;
  categoryLabel: string;
  ratios: FundamentalsRatio[];
}

/** Group the scorecard ratios by category, preserving the first-seen order. */
export function groupByCategory(
  ratios: readonly FundamentalsRatio[],
): RatioCategoryGroup[] {
  const groups: RatioCategoryGroup[] = [];
  const byCategory = new Map<string, RatioCategoryGroup>();
  for (const ratio of ratios) {
    const existing = byCategory.get(ratio.category);
    if (existing) {
      existing.ratios.push(ratio);
      continue;
    }
    const group: RatioCategoryGroup = {
      category: ratio.category,
      categoryLabel: ratio.category_label,
      ratios: [ratio],
    };
    byCategory.set(ratio.category, group);
    groups.push(group);
  }
  return groups;
}

/** The five-number summary a box plot needs. */
export interface BoxPlotStats {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

/**
 * Turn a peer summary into a box-plot five-number summary.
 *
 * Falls back to p5/p95 for the whiskers and quartiles when the explicit
 * quartiles are absent, and clamps the values into a non-decreasing order so a
 * degenerate summary can never draw an inverted box. Returns ``null`` when the
 * peer set is empty or the summary is incomplete.
 */
export function boxPlotStats(
  peers: FundamentalsPeerStatistic | undefined,
): BoxPlotStats | null {
  if (!peers || peers.n === 0) {
    return null;
  }
  const median = peers.median ?? null;
  const q1 = peers.q1 ?? peers.p5 ?? null;
  const q3 = peers.q3 ?? peers.p95 ?? null;
  const min = peers.minimum ?? peers.p5 ?? null;
  const max = peers.maximum ?? peers.p95 ?? null;
  if (median === null || q1 === null || q3 === null || min === null || max === null) {
    return null;
  }
  return {
    min: Math.min(min, q1),
    q1: Math.min(q1, median),
    median,
    q3: Math.max(q3, median),
    max: Math.max(max, q3),
  };
}

export type FundamentalsViewState =
  | "loading"
  | "ready"
  | "empty"
  | "no_fundamentals"
  | "unavailable"
  | "error";

function statusOf(error: unknown): number | null {
  if (typeof error === "object" && error !== null && "status" in error) {
    const status = (error as { status?: unknown }).status;
    return typeof status === "number" ? status : null;
  }
  return null;
}

/**
 * Decide which state the Fundamentals tab renders.
 *
 * A 404 (no stored ratios for the ticker) is the friendly "No fundamentals loaded
 * for this ticker yet" state, not an error; a 422/"no data" is the "run the
 * precompute job" state. Everything else is a genuine request error.
 */
export function fundamentalsViewState(input: {
  loading: boolean;
  error: unknown;
  comparison: FundamentalsComparison | null;
}): FundamentalsViewState {
  if (input.loading) {
    return "loading";
  }
  if (input.error !== null && input.error !== undefined) {
    if (statusOf(input.error) === 404) {
      return "no_fundamentals";
    }
    const message = input.error instanceof Error ? input.error.message : String(input.error);
    return /no stored|not available|run the precompute|no data/i.test(message)
      ? "unavailable"
      : "error";
  }
  const ratios = input.comparison?.ratios ?? [];
  return ratios.length === 0 ? "empty" : "ready";
}

/** Human-readable reporting period, e.g. "2026-09-30 (trailing twelve months)". */
export function reportingPeriodLabel(
  period: string | null | undefined,
  periodType: string | null | undefined,
): string {
  if (!period) return "latest period";
  const typeLabels: Record<string, string> = {
    ttm: "trailing twelve months",
    annual: "annual",
    quarter: "quarter",
  };
  const typeLabel = periodType ? typeLabels[periodType] : undefined;
  return typeLabel ? `${period} (${typeLabel})` : period;
}
