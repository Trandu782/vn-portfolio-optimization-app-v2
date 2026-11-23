"use client";

/**
 * Universe selector over the single app store.
 *
 * The Universe page writes the built selection here and every other page reads
 * it from the same place, so leaving and returning to a page keeps the tickers,
 * date range and result.
 */

import type { UniverseSelection } from "./app-store";
import { useAppStore } from "./app-store-context";

export type { UniverseSelection };

export interface UniverseContextValue {
  /** The most recently built universe, or null before the first build. */
  selection: UniverseSelection | null;
  /** Replace the stored selection. */
  setSelection: (selection: UniverseSelection) => void;
  /** Clear the stored selection. */
  clearSelection: () => void;
}

export function useUniverse(): UniverseContextValue {
  const { selection, setSelection, clearSelection } = useAppStore();
  return { selection, setSelection, clearSelection };
}
