"use client";

import { Card } from "@/components/ui/Card";
import { inputClass, inputCompactClass, selectClass } from "@/components/ui/Field";
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
    <Card className="space-y-4">
      {facets.length > 0 && (
        <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          Facet applied from the Optimize filter: {facets.join(" \u00b7 ")}. The Sector tab
          analyses all ICB sectors within that narrower universe.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-1.5 text-sm">
          <span className="block font-medium text-fg">Benchmark</span>
          <select
            value={benchmark}
            onChange={(event) => onBenchmark(event.target.value)}
            className={`${selectClass} w-full`}
          >
            {BENCHMARKS.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="block text-xs text-fg-muted">
            Banks and real estate are a large share of VN30/VN100, so beta against them is
            mechanically inflated.
          </span>
        </label>

        <label className="block space-y-1.5 text-sm">
          <span className="block font-medium text-fg">Liquidity preset</span>
          <select
            value={preset}
            onChange={(event) => onPreset(event.target.value)}
            className={`${selectClass} w-full`}
          >
            {PRESETS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="block text-xs text-fg-muted">
            Market cap is full (free-float is unavailable); ADTV and ADV are the real guards.
          </span>
        </label>

        <div className="space-y-1.5 text-sm">
          <label htmlFor="sector-weighting" className="block font-medium text-fg">
            Weighting
          </label>
          <select
            id="sector-weighting"
            value={weighting}
            onChange={(event) => onWeighting(event.target.value as "market_cap" | "equal")}
            className={`${selectClass} w-full`}
          >
            <option value="market_cap">Full market cap</option>
            <option value="equal">Equal weight</option>
          </select>
        </div>

        <label className="block space-y-1.5 text-sm">
          <span className="block font-medium text-fg">Single-stock cap (%)</span>
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
            className={`${inputClass} w-full font-mono tabular-nums`}
          />
          <span className="block text-xs text-fg-muted">
            Default 15% on full market cap. Clear the box for no cap. Ignored for equal weight.
          </span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-fg">Timeframe</span>
        <div
          role="group"
          aria-label="Sector timeframe"
          className="inline-flex flex-wrap overflow-hidden rounded-lg border border-strong bg-raised"
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
                className={`min-h-[40px] md:min-h-0 px-3 py-1.5 text-xs font-medium transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent ${
                  active
                    ? "bg-accent text-white"
                    : "text-fg-secondary hover:bg-surface hover:text-fg"
                }`}
              >
                {item}
              </button>
            );
          })}
        </div>
      </div>

      {timeframe.preset === "Custom" && (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-2">
            <span className="text-fg-secondary">Start</span>
            <input
              type="date"
              value={timeframe.start}
              max={timeframe.end || undefined}
              onChange={(event) =>
                onTimeframe({ preset: "Custom", start: event.target.value, end: timeframe.end })
              }
              className={`${inputCompactClass} font-mono tabular-nums`}
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-fg-secondary">End</span>
            <input
              type="date"
              value={timeframe.end}
              min={timeframe.start || undefined}
              onChange={(event) =>
                onTimeframe({ preset: "Custom", start: timeframe.start, end: event.target.value })
              }
              className={`${inputCompactClass} font-mono tabular-nums`}
            />
          </label>
        </div>
      )}

      <label className="flex min-h-[36px] cursor-pointer items-center gap-2 text-xs text-fg-secondary">
        <input
          type="checkbox"
          checked={includeDefaultExcluded}
          onChange={(event) => onIncludeDefaultExcluded(event.target.checked)}
          className="h-4 w-4 accent-accent"
        />
        <span>Include tickers the adjustment checks drop by default</span>
      </label>
    </Card>
  );
}
