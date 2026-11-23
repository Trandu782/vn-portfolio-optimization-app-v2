"use client";

/**
 * Sector Analysis control header (docs/V2_SPEC.md section 3.2).
 *
 * Benchmark, sector timeframe, liquidity preset, weighting (full market cap with an
 * optional single-stock cap, or equal weight) and the include-default-excluded toggle.
 * Every change is written to the shared store by the parent; this component only reads
 * and calls the callbacks. Any index/exchange facet carried over from the Optimize tab
 * is labelled so the user knows the view is narrowed.
 */

import { SECTOR_TIMEFRAME_PRESETS, type SectorTimeframeSelection } from "@/lib/sector-timeframe";

const BENCHMARKS = [
  { code: "VNINDEX", label: "VN-Index" },
  { code: "VN30", label: "VN30" },
  { code: "VN100", label: "VN100" },
];

const PRESETS = [
  { id: "small_retail", label: "Small retail (< 1B VND)" },
  { id: "standard_retail", label: "Standard retail (1B\u201310B VND)" },
  { id: "high_liquidity", label: "High liquidity (\u2265 10B VND)" },
  { id: "all_stocks", label: "All stocks" },
];

export interface SectorControlsProps {
  benchmark: string;
  preset: string;
  weighting: "market_cap" | "equal";
  capPercent: number | null;
  includeDefaultExcluded: boolean;
  timeframe: SectorTimeframeSelection;
  indexes: string[];
  exchange: string | null;
  onBenchmark: (code: string) => void;
  onPreset: (id: string) => void;
  onWeighting: (weighting: "market_cap" | "equal") => void;
  onCapPercent: (percent: number | null) => void;
  onIncludeDefaultExcluded: (value: boolean) => void;
  onTimeframe: (selection: SectorTimeframeSelection) => void;
}

export function SectorControls({
  benchmark,
  preset,
  weighting,
  capPercent,
  includeDefaultExcluded,
  timeframe,
  indexes,
  exchange,
  onBenchmark,
  onPreset,
  onWeighting,
  onCapPercent,
  onIncludeDefaultExcluded,
  onTimeframe,
}: SectorControlsProps) {
  const facets: string[] = [];
  if (indexes.length > 0) facets.push(`Index ${indexes.join(" + ")}`);
  if (exchange) facets.push(`Exchange ${exchange}`);

  return (
    <div className="space-y-3 rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      {facets.length > 0 && (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          Facet applied from the Optimize filter: {facets.join(" \u00b7 ")}. The Sector tab
          analyses all ICB sectors within that narrower universe.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="block font-medium">Benchmark</span>
          <select
            value={benchmark}
            onChange={(event) => onBenchmark(event.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          >
            {BENCHMARKS.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
            Banks and real estate are a large share of VN30/VN100, so beta against them is
            mechanically inflated.
          </span>
        </label>

        <label className="block text-sm">
          <span className="block font-medium">Liquidity preset</span>
          <select
            value={preset}
            onChange={(event) => onPreset(event.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          >
            {PRESETS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
            Market cap is full (free-float is unavailable); ADTV and ADV are the real guards.
          </span>
        </label>

        <div className="block text-sm">
          <span className="block font-medium">Weighting</span>
          <select
            value={weighting}
            onChange={(event) => onWeighting(event.target.value as "market_cap" | "equal")}
            className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          >
            <option value="market_cap">Full market cap</option>
            <option value="equal">Equal weight</option>
          </select>
        </div>

        <label className="block text-sm">
          <span className="block font-medium">Single-stock cap (%)</span>
          <input
            type="number"
            min={0.1}
            max={100}
            step={0.5}
            disabled={weighting === "equal"}
            value={capPercent ?? ""}
            onChange={(event) => {
              const raw = event.target.value.trim();
              onCapPercent(raw === "" ? null : Number(raw));
            }}
            placeholder="No cap"
            className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-900"
          />
          <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
            Default 15% on full market cap. Clear the box for no cap. Ignored for equal weight.
          </span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Timeframe</span>
        <div
          role="group"
          aria-label="Sector timeframe"
          className="inline-flex flex-wrap overflow-hidden rounded-md border border-gray-300 dark:border-gray-700"
        >
          {SECTOR_TIMEFRAME_PRESETS.map((item) => {
            const active = timeframe.preset === item;
            return (
              <button
                key={item}
                type="button"
                onClick={() =>
                  onTimeframe(
                    item === "Custom"
                      ? { preset: "Custom", start: timeframe.start, end: timeframe.end }
                      : { preset: item, start: "", end: "" },
                  )
                }
                aria-pressed={active}
                className={
                  active
                    ? "bg-blue-600 px-2.5 py-1 text-xs font-medium text-white"
                    : "px-2.5 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-800"
                }
              >
                {item}
              </button>
            );
          })}
        </div>
      </div>

      {timeframe.preset === "Custom" && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1">
            <span className="text-gray-600 dark:text-gray-300">Start</span>
            <input
              type="date"
              value={timeframe.start}
              max={timeframe.end || undefined}
              onChange={(event) =>
                onTimeframe({ preset: "Custom", start: event.target.value, end: timeframe.end })
              }
              className="rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="flex items-center gap-1">
            <span className="text-gray-600 dark:text-gray-300">End</span>
            <input
              type="date"
              value={timeframe.end}
              min={timeframe.start || undefined}
              onChange={(event) =>
                onTimeframe({ preset: "Custom", start: timeframe.start, end: event.target.value })
              }
              className="rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
        </div>
      )}

      <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
        <input
          type="checkbox"
          checked={includeDefaultExcluded}
          onChange={(event) => onIncludeDefaultExcluded(event.target.checked)}
        />
        Include tickers the adjustment checks drop by default
      </label>
    </div>
  );
}
