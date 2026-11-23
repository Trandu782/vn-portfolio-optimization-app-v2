"use client";

/**
 * Per-tab timeframe selector over the single app store.
 *
 * The Optimize and Risk pages each keep their own window, but both live in the
 * one persisted store (`app-store.ts`) so switching tabs or reloading keeps the
 * choice, exactly like the shared universe.
 */

import type { Timeframes } from "./app-store";
import { useAppStore } from "./app-store-context";
import type { TimeframeSelection } from "./timeframe";

export type { Timeframes };

export interface TimeframeContextValue {
  /** The persisted timeframe for each tab. */
  timeframes: Timeframes;
  /** Replace one tab's timeframe. */
  setTimeframe: (tab: "optimize" | "risk", selection: TimeframeSelection) => void;
}

export function useTimeframes(): TimeframeContextValue {
  const { timeframes, setTimeframe } = useAppStore();
  return { timeframes, setTimeframe };
}
