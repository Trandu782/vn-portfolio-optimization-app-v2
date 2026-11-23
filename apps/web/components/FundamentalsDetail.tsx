"use client";

/**
 * Fetch one ticker's peer comparison and render it with every state handled
 * (docs/V2_SPEC.md 3.3): loading, the friendly "no fundamentals loaded yet" for an
 * uncovered ticker, the "run the precompute job" state, a genuine error and the
 * empty peer set. Shared by the sub-tab and the ticker drawer.
 */

import { useEffect, useState } from "react";

import {
  fetchFundamentals,
  type FundamentalsComparison,
  type PeerVariant,
} from "@/lib/api";
import { fundamentalsViewState } from "@/lib/fundamentals";

import { FundamentalsPanel } from "./FundamentalsPanel";

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function FundamentalsDetail({
  symbol,
  peerVariant = "all",
  preset,
}: {
  symbol: string | null;
  peerVariant?: PeerVariant;
  preset?: string;
}) {
  const [comparison, setComparison] = useState<FundamentalsComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!symbol) {
      setComparison(null);
      setError(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    fetchFundamentals(symbol, { peer_variant: peerVariant, preset })
      .then((payload) => {
        if (active) setComparison(payload);
      })
      .catch((err: unknown) => {
        if (active) {
          setComparison(null);
          setError(err);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [symbol, peerVariant, preset]);

  if (!symbol) {
    return (
      <p className="rounded-lg border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
        Search for a ticker above to see its fundamentals against the sector.
      </p>
    );
  }

  const state = fundamentalsViewState({ loading, error, comparison });

  if (state === "loading") {
    return (
      <p className="rounded-lg border border-gray-200 p-4 text-sm text-gray-500 dark:border-gray-800 dark:text-gray-400">
        Loading {symbol} fundamentals&hellip;
      </p>
    );
  }
  if (state === "no_fundamentals") {
    return (
      <p className="rounded-lg border border-gray-200 p-4 text-sm text-gray-600 dark:border-gray-800 dark:text-gray-300">
        No fundamentals loaded for this ticker yet ({symbol.toUpperCase()}). It has no stored
        financial ratios in the current dataset.
      </p>
    );
  }
  if (state === "unavailable") {
    return (
      <p className="rounded-lg bg-amber-50 p-4 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
        Fundamentals data is not available yet: run the precompute job to populate the ratio
        tables.
      </p>
    );
  }
  if (state === "error") {
    return (
      <p className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
        {message(error)}
      </p>
    );
  }
  if (state === "empty" || comparison === null) {
    return (
      <p className="rounded-lg border border-gray-200 p-4 text-sm text-gray-500 dark:border-gray-800 dark:text-gray-400">
        No ratios are available for {symbol.toUpperCase()} under this peer set.
      </p>
    );
  }
  return <FundamentalsPanel comparison={comparison} />;
}
