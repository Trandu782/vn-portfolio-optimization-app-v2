"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  fetchSectorAnalytics,
  type SectorAnalytics,
  type SectorAnalyticsQuery,
} from "@/lib/api";
import { useAppStore } from "@/lib/app-store-context";
import {
  analyticsViewState,
  benchmarkLabel as benchmarkDisplayName,
  sectorColor,
  sortSectorRows,
  toSectorRow,
  type SectorSortKey,
  type SortDirection,
} from "@/lib/sector-analysis";
import {
  toSectorRequest,
  validateSectorTimeframe,
  type SectorTimeframeSelection,
} from "@/lib/sector-timeframe";

import { SectorBetaTable } from "./SectorBetaTable";
import { SectorControls } from "./SectorControls";
import { SectorExcludedPanel } from "./SectorExcludedPanel";
import { RelativeSectorChart, type RelativeSectorSeries } from "./charts/RelativeSectorChart";
import { SectorCorrelationHeatmap } from "./charts/SectorCorrelationHeatmap";
import { SectorScatter } from "./charts/SectorScatter";

function weightingLabel(weighting: string, capPercent: number | null): string {
  if (weighting === "equal") return "Equal weight";
  return capPercent === null
    ? "Full market cap (no single-stock cap)"
    : `Full market cap (max ${capPercent}% per stock)`;
}

export function SectorAnalysis() {
  const { v2Filter, setV2Filter, timeframes, setSectorTimeframe } = useAppStore();
  const router = useRouter();

  const [data, setData] = useState<SectorAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SectorSortKey>("period_return");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showScatter, setShowScatter] = useState(false);

  const {
    benchmark,
    preset,
    indexes,
    exchange,
    weighting,
    capPercent,
    excludeAdjustmentFlagged,
    includeDefaultExcluded,
  } = v2Filter;
  const sectorTimeframe = timeframes.sector;

  const query = useMemo<SectorAnalyticsQuery>(() => {
    const tf = toSectorRequest(sectorTimeframe);
    return {
      benchmark,
      timeframe: tf.timeframe,
      custom_start: tf.custom_start,
      custom_end: tf.custom_end,
      liquidity_preset: preset,
      indexes,
      exchange,
      weighting,
      cap_percent: weighting === "market_cap" ? capPercent : null,
      include_default_excluded: includeDefaultExcluded,
      exclude_adjustment_flagged: excludeAdjustmentFlagged,
    };
  }, [
    benchmark,
    preset,
    indexes,
    exchange,
    weighting,
    capPercent,
    excludeAdjustmentFlagged,
    includeDefaultExcluded,
    sectorTimeframe,
  ]);

  useEffect(() => {
    let active = true;
    const customError = validateSectorTimeframe(sectorTimeframe);
    if (customError) {
      setError(customError);
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchSectorAnalytics(query)
      .then((payload) => {
        if (active) setData(payload);
      })
      .catch((err: unknown) => {
        if (active) {
          setData(null);
          setError(err instanceof Error ? err.message : "Failed to load the sector analysis.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [query, sectorTimeframe]);

  useEffect(() => {
    if (!data) return;
    const ok = new Set(
      (data.groups ?? [])
        .filter((group) => group.index.status === "ok")
        .map((group) => group.index.group),
    );
    setSelected(ok);
  }, [data]);

  const rows = useMemo(
    () => sortSectorRows((data?.groups ?? []).map(toSectorRow), sortKey, sortDirection),
    [data, sortKey, sortDirection],
  );

  const series = useMemo<RelativeSectorSeries[]>(() => {
    return (data?.groups ?? [])
      .filter((group) => group.index.status === "ok")
      .map((group, index) => ({
        id: group.index.group,
        label: group.index.group,
        color: sectorColor(index),
        points: group.index.cumulative_returns ?? [],
      }));
  }, [data]);

  const colorBySector = useMemo(
    () => new Map(series.map((line) => [line.id, line.color])),
    [series],
  );

  const viewState = analyticsViewState(loading, error, (data?.groups ?? []).length);

  const handleSort = useCallback((key: SectorSortKey) => {
    setSortKey((currentKey) => {
      if (currentKey === key) {
        setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
        return currentKey;
      }
      setSortDirection(key === "name" ? "asc" : "desc");
      return key;
    });
  }, []);

  const toggleSector = useCallback((name: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const sendToOptimizer = useCallback(() => {
    setV2Filter({ ...v2Filter, sectors: [...selected] });
    router.push("/optimize");
  }, [selected, setV2Filter, v2Filter, router]);

  const windowLabel = data ? `${data.window.start} to ${data.window.end}` : "";

  return (
    <section className="space-y-6">
      <SectorControls
        benchmark={benchmark}
        preset={preset}
        weighting={weighting}
        capPercent={capPercent}
        includeDefaultExcluded={includeDefaultExcluded}
        timeframe={sectorTimeframe}
        indexes={indexes}
        exchange={exchange}
        onBenchmark={(code) => setV2Filter({ ...v2Filter, benchmark: code })}
        onPreset={(id) => setV2Filter({ ...v2Filter, preset: id })}
        onWeighting={(next) => setV2Filter({ ...v2Filter, weighting: next })}
        onCapPercent={(percent) => setV2Filter({ ...v2Filter, capPercent: percent })}
        onIncludeDefaultExcluded={(value) =>
          setV2Filter({ ...v2Filter, includeDefaultExcluded: value })
        }
        onTimeframe={(selection: SectorTimeframeSelection) => setSectorTimeframe(selection)}
      />

      {viewState === "loading" && (
        <Card className="text-sm text-fg-muted">Loading sector analysis&hellip;</Card>
      )}
      {viewState === "unavailable" && (
        <p className="rounded-lg border border-warn-border bg-warn-subtle p-4 text-sm text-warn">
          V2 data not available: run the precompute job to populate the sector tables.
        </p>
      )}
      {viewState === "error" && (
        <p className="rounded-lg border border-negative/25 bg-negative-subtle p-4 text-sm text-negative">
          {error}
        </p>
      )}
      {viewState === "empty" && (
        <Card className="text-sm text-fg-muted">
          No sectors pass the current filters. Try a looser liquidity preset or clear the index facet.
        </Card>
      )}

      {viewState === "ready" && data && (
        <>
          <RelativeSectorChart
            benchmarkLabel={benchmarkDisplayName(data.benchmark)}
            benchmarkPoints={data.benchmark_returns ?? []}
            series={series}
            windowLabel={windowLabel}
          />

          <SectorBetaTable
            rows={rows}
            selected={selected}
            onToggle={toggleSector}
            sortKey={sortKey}
            sortDirection={sortDirection}
            onSort={handleSort}
          />

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              onClick={sendToOptimizer}
              disabled={selected.size === 0}
            >
              Send {selected.size} sector(s) to Optimizer
            </Button>
            <Button
              variant="secondary"
              onClick={() => setShowScatter((value) => !value)}
            >
              {showScatter ? "Hide" : "Show"} return vs beta
            </Button>
          </div>

          {showScatter && <SectorScatter rows={rows} colorBySector={colorBySector} />}

          {data.correlation && (
            <SectorCorrelationHeatmap
              correlation={data.correlation}
              windowLabel={windowLabel}
              averageCorrelation={data.correlation.average_pairwise_correlation ?? null}
            />
          )}

          <SectorExcludedPanel
            items={data.default_excluded ?? []}
            outsideWindow={data.default_excluded_outside_window ?? []}
            includeDefaultExcluded={data.include_default_excluded}
            onToggle={(value) => setV2Filter({ ...v2Filter, includeDefaultExcluded: value })}
            flagsAvailable={data.flags_available}
            flagsPolicyCurrent={data.flags_policy_current}
          />

          <dl className="grid gap-3 rounded-xl border border-hairline bg-raised/50 p-4 text-xs text-fg-secondary sm:grid-cols-2">
            <div>
              <dt className="font-medium text-fg">Data as of</dt>
              <dd className="mt-0.5 font-mono tabular-nums">{data.data_as_of}</dd>
            </div>
            <div>
              <dt className="font-medium text-fg">Weighting basis</dt>
              <dd className="mt-0.5">{weightingLabel(data.weighting, capPercent)}</dd>
            </div>
            <div>
              <dt className="font-medium text-fg">Price basis</dt>
              <dd className="mt-0.5 font-mono">{data.price_adjustment_basis ?? "unknown"}</dd>
            </div>
            <div>
              <dt className="font-medium text-fg">Volume basis</dt>
              <dd className="mt-0.5 font-mono">{data.volume_basis ?? "unknown"}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="font-medium text-fg">Current-constituents index</dt>
              <dd className="mt-0.5 leading-relaxed">
                Constituents are fixed at the end date and the current ICB level-2 sector map
                is applied to history. A sector needs at least 3 constituents to publish.
              </dd>
            </div>
          </dl>

          <Card compact className="text-xs text-fg-muted">
            <p className="font-medium text-fg-secondary">Limitations</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5">
              <li>Returns across a trading halt are dropped that day, not compounded over the gap.</li>
              <li>Rights-issue (ISS) adjustments are not verified; treat them with caution.</li>
              <li>
                Market cap is full, not free-float, so a low-float large cap can look cheaper to
                trade than it is.
              </li>
              <li>Sectors are today&apos;s ICB level-2 classification applied to history.</li>
            </ul>
          </Card>
        </>
      )}
    </section>
  );
}
