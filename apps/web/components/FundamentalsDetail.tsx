"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/ui/Card";
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
      <p className="rounded-xl border border-dashed border-strong p-6 text-sm text-fg-muted">
        Search for a ticker above to see its fundamentals against the sector.
      </p>
    );
  }

  const state = fundamentalsViewState({ loading, error, comparison });

  if (state === "loading") {
    return (
      <Card className="text-sm text-fg-muted">
        Loading <span className="font-mono font-medium text-fg">{symbol}</span> fundamentals&hellip;
      </Card>
    );
  }
  if (state === "no_fundamentals") {
    return (
      <Card className="text-sm text-fg-secondary">
        No fundamentals loaded for this ticker yet (
        <span className="font-mono font-medium text-fg">{symbol.toUpperCase()}</span>). It has no
        stored financial ratios in the current dataset.
      </Card>
    );
  }
  if (state === "unavailable") {
    return (
      <p className="rounded-lg border border-warn-border bg-warn-subtle p-4 text-sm text-warn">
        Fundamentals data is not available yet: run the precompute job to populate the ratio
        tables.
      </p>
    );
  }
  if (state === "error") {
    return (
      <p className="rounded-lg border border-negative/25 bg-negative-subtle p-4 text-sm text-negative">
        {message(error)}
      </p>
    );
  }
  if (state === "empty" || comparison === null) {
    return (
      <Card className="text-sm text-fg-muted">
        No ratios are available for{" "}
        <span className="font-mono font-medium text-fg">{symbol.toUpperCase()}</span> under this
        peer set.
      </Card>
    );
  }
  return <FundamentalsPanel comparison={comparison} />;
}
