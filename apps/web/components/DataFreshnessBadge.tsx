"use client";

import { useEffect, useState } from "react";

import { fetchDataFreshness, type DataFreshness } from "@/lib/api";

/**
 * Global badge showing the latest stored price date and the provider that owns the
 * freshest bar, sourced from GET /api/v1/data/freshness. The API reports the V2
 * source (e.g. `ssi_statistics`) when V2 owns the latest bar and falls back to the
 * first healthy provider in PROVIDER_ORDER otherwise, so this badge matches the
 * source the Portfolio page values against. Amber when a provider is down or the
 * latest bar looks stale; when every provider is unhealthy it reports that cached
 * (possibly stale) data is served.
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
        className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400"
      >
        data: unknown
      </span>
    );
  }

  if (!freshness) {
    return (
      <span className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
        data: ...
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
      className={
        needsAttention
          ? "rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-200"
          : "rounded-full bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"
      }
    >
      data: {active} · {latest}
      {down.length > 0 ? ` · failover: ${down.map((status) => status.id).join(", ")}` : ""}
    </span>
  );
}
