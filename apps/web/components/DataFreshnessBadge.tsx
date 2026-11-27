"use client";

import { useEffect, useState } from "react";

import { fetchDataFreshness, type DataFreshness } from "@/lib/api";

/**
 * Global badge showing the latest stored price date and the provider that owns the
 * freshest bar, sourced from GET /api/v1/data/freshness.
 */
export function DataFreshnessBadge() {
  const [freshness, setFreshness] = useState<DataFreshness | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    fetchDataFreshness()
      .then((data) => {
        if (active) {
          setFreshness(data);
          setError(false);
        }
      })
      .catch(() => {
        if (active) {
          setError(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (error) {
    return (
      <span
        title="Data freshness is unavailable"
        className="inline-flex items-center gap-2 rounded-md border border-hairline bg-surface px-2.5 py-1 font-mono text-xs tabular-nums text-fg-muted"
      >
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-fg-muted" aria-hidden="true" />
        <span>offline</span>
      </span>
    );
  }

  if (!freshness) {
    return (
      <span className="inline-flex items-center gap-2 rounded-md border border-hairline bg-surface px-2.5 py-1 font-mono text-xs tabular-nums text-fg-muted">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-fg-muted" aria-hidden="true" />
        <span>syncing</span>
      </span>
    );
  }

  const down = freshness.providers.filter((status) => !status.healthy);
  const active = freshness.primary ?? "cached";
  const latest = freshness.latest_date ?? "no data";
  const warningText = down
    .map((status) => `${status.id} down (${status.last_error_type ?? "unknown"})`)
    .join("; ");
  const title = [
    `Source of freshest prices: ${active}`,
    `Latest stored price date across all tickers: ${latest}`,
    freshness.stale ? "Prices may be stale" : "Prices are current",
    warningText ? `Failover: ${warningText}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const needsAttention = freshness.primary === null || freshness.stale || down.length > 0;

  return (
    <span
      title={title}
      className="inline-flex items-center gap-2 rounded-md border border-hairline bg-surface px-2.5 py-1 font-mono text-xs tabular-nums text-fg-secondary"
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          needsAttention ? "bg-warn" : "bg-positive"
        }`}
        aria-hidden="true"
      />
      <span className="whitespace-nowrap">
        {active} · {latest}
        {down.length > 0 ? ` · failover: ${down.map((status) => status.id).join(", ")}` : ""}
      </span>
    </span>
  );
}
