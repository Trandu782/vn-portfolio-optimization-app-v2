/**
 * Product guardrails for the simplified Optimize page.
 *
 * Mirrors `packages/core/core/optimize/guardrails.py` so the UI can compute the
 * default per-position weight cap and the universe-size warnings/limit without a
 * round trip, and so the rules are unit-tested in the browser runtime too.
 */

/** Below this many stocks the efficient frontier is not meaningful. */
export const MIN_MEANINGFUL_STOCKS = 5;
/** Above this many stocks the sample covariance is unreliable. */
export const MAX_RELIABLE_STOCKS = 20;
/** Hard cap on the number of stocks in one optimization. */
export const HARD_MAX_STOCKS = 30;
/** Floor of the default weight cap, regardless of the portfolio size. */
export const DEFAULT_MAX_WEIGHT_FLOOR = 0.25;
/** The default cap is at least this many equal slices (1.5 / n). */
export const DEFAULT_MAX_WEIGHT_MULTIPLE = 1.5;

/** Return the default per-position weight cap for `nAssets` stocks (max(25%, 1.5 / n)). */
export function defaultMaxWeight(nAssets: number): number {
  if (nAssets <= 0) return DEFAULT_MAX_WEIGHT_FLOOR;
  return Math.min(1, Math.max(DEFAULT_MAX_WEIGHT_FLOOR, DEFAULT_MAX_WEIGHT_MULTIPLE / nAssets));
}

/** A weight cap and whether it had to be raised to stay fully investable. */
export interface FeasibleMaxWeight {
  value: number;
  raised: boolean;
}

/** Return a feasible cap, raising it to `1 / n` when `n * cap < 1`. */
export function feasibleMaxWeight(nAssets: number, requested: number): FeasibleMaxWeight {
  if (nAssets <= 0) return { value: requested, raised: false };
  const minimum = 1 / nAssets;
  if (requested * nAssets < 1) {
    return { value: minimum, raised: true };
  }
  return { value: requested, raised: false };
}

/** Plain-language warnings for a universe of `nAssets` stocks. */
export function universeSizeWarnings(nAssets: number): string[] {
  const warnings: string[] = [];
  if (nAssets < MIN_MEANINGFUL_STOCKS) {
    warnings.push(
      `Only ${nAssets} stock(s): the efficient frontier is not meaningful below ${MIN_MEANINGFUL_STOCKS}.`,
    );
  }
  if (nAssets > MAX_RELIABLE_STOCKS) {
    warnings.push(
      `${nAssets} stocks is a lot: the sample covariance becomes unreliable above ${MAX_RELIABLE_STOCKS}.`,
    );
  }
  return warnings;
}

/** True when `nAssets` exceeds the hard cap (or the provided configured limit). */
export function exceedsHardMax(nAssets: number, limit: number = HARD_MAX_STOCKS): boolean {
  return nAssets > limit;
}