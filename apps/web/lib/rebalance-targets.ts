/**
 * Pure helpers that turn weights into editable Rebalance target rows.
 *
 * The Rebalance page starts its target list from the mix saved with "Use this
 * portfolio" on the Optimize page (the `chosenPortfolio` slice of the shared
 * store) and falls back to the current portfolio weights. Weights are fractions
 * of total value; the page edits percentages. Percentages are truncated (not
 * rounded) so a fully invested mix can never be rejected for summing to just
 * over 100%. This module has no React or DOM imports, so it is unit-tested with
 * Node's built-in test runner.
 */

import type { TargetWeightRow } from "./rebalance-csv";

/** Convert a fraction to a percentage with two decimals, truncating the rest. */
function toPercent(weight: number): number {
  // The epsilon absorbs binary noise such as 0.29 * 10_000 = 2899.9999999999995.
  return Math.floor(weight * 10_000 + 1e-9) / 100;
}

/**
 * Convert a weights map (fractions summing to at most 1) into target rows.
 *
 * Empty codes, non-finite values and zero weights are dropped (the frontier
 * often returns exact zeros), rows are sorted heaviest first, and symbols are
 * upper-cased. The percent total never exceeds 100.
 */
export function targetRowsFromWeights(
  weights: Readonly<Record<string, number>>,
): TargetWeightRow[] {
  return Object.entries(weights)
    .filter(([symbol, weight]) => symbol.trim() !== "" && Number.isFinite(weight) && weight > 0)
    .map(([symbol, weight]) => ({
      symbol: symbol.trim().toUpperCase(),
      weight_percent: toPercent(weight),
    }))
    .filter((row) => row.weight_percent > 0)
    .sort((a, b) => b.weight_percent - a.weight_percent || a.symbol.localeCompare(b.symbol));
}

/** The share of the valuation needed to build target rows. */
export interface ValuedHolding {
  symbol: string;
  shares: number;
  weight: number;
}

/**
 * Convert valued holdings into target rows.
 *
 * Wishlist entries (`shares == 0`) have no market value and are skipped, and
 * duplicate codes are merged so the resulting map stays one row per symbol.
 */
export function targetRowsFromHoldings(holdings: readonly ValuedHolding[]): TargetWeightRow[] {
  const weights: Record<string, number> = {};
  for (const holding of holdings) {
    if (holding.shares <= 0 || !Number.isFinite(holding.weight)) {
      continue;
    }
    const code = holding.symbol.trim().toUpperCase();
    if (code === "") {
      continue;
    }
    weights[code] = (weights[code] ?? 0) + holding.weight;
  }
  return targetRowsFromWeights(weights);
}
