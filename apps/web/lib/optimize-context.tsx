"use client";

/**
 * Optimization result selector over the single app store.
 *
 * The Optimize page publishes its result here; the Risk and Rebalance pages read
 * it from the same store, so it survives navigation and reloads.
 */

import type { OptimizeResult } from "./api";
import { useAppStore } from "./app-store-context";

export interface OptimizeContextValue {
  /** The most recent optimization result, or null before the first run. */
  result: OptimizeResult | null;
  /**
   * The mix saved with "Use this portfolio" (fractions of total value), or
   * `null` before the user chooses one. Risk and Rebalance read it from here.
   */
  chosenWeights: Record<string, number> | null;
  /** Publish a completed optimization result (also records it as chosen). */
  setResult: (result: OptimizeResult) => void;
  /** Clear the stored result. */
  clearResult: () => void;
}

export function useOptimize(): OptimizeContextValue {
  const { optimizeResult, setOptimizeResult, clearOptimizeResult, chosenPortfolio } =
    useAppStore();
  return {
    result: optimizeResult,
    chosenWeights: chosenPortfolio?.weights ?? null,
    setResult: setOptimizeResult,
    clearResult: clearOptimizeResult,
  };
}
