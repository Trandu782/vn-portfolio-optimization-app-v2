"use client";

/**
 * Historical performance: growth of 100 for each portfolio versus the benchmark.
 *
 * Features required by the product: visible axis ticks, a dashed baseline at
 * 100, a crosshair tooltip (date, level and percent versus the start), a legend
 * that shows/hides a series and a brush for drag-to-zoom with a reset button.
 * The summary table is explicitly labelled "Full timeframe" so it is never
 * mistaken for the zoomed range.
 */

import { useMemo, useState } from "react";
import {
  Brush,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { PerformanceResult } from "@/lib/api";
import {
  AXIS_TEXT,
  AXIS_TICK,
  CHART_COLORS,
  GRID_STROKE,
  formatDateTick,
  formatLevel,
  formatPercent,
  formatSignedPercent,
} from "@/lib/chart-theme";

import { TooltipBox } from "./TooltipBox";

export interface PerformanceSeries {
  id: string;
  label: string;
  color: string;
  performance: PerformanceResult;
}

interface TooltipEntry {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string | Array<number | string>;
  color?: string;
}

interface PerformanceTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: TooltipEntry[];
}

function PerformanceTooltip({ active, label, payload }: PerformanceTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const rows = payload.filter(
    (entry) => typeof entry.value === "number" && Number.isFinite(entry.value),
  );
  if (rows.length === 0) return null;
  return (
    <TooltipBox>
      <p className="font-medium">{String(label ?? "")}</p>
      <ul className="mt-1 space-y-0.5">
        {rows.map((entry) => {
          const level = entry.value as number;
          return (
            <li key={String(entry.dataKey ?? entry.name)} className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: entry.color ?? "#6b7280" }}
                  aria-hidden
                />
                {String(entry.name ?? "")}
              </span>
              <span className="ml-auto tabular-nums">
                {formatLevel(level)}{" "}
                <span className="text-gray-500 dark:text-gray-400">
                  ({formatSignedPercent(level / 100 - 1)})
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </TooltipBox>
  );
}

type ChartRow = Record<string, string | number | null>;

/** Align every series' growth to the shared date axis, carrying gaps forward. */
function buildRows(dates: string[], series: PerformanceSeries[]): ChartRow[] {
  const maps = series.map((item) => {
    const byDate = new Map<string, number>();
    item.performance.dates.forEach((day, index) => {
      byDate.set(day, item.performance.growth[index]);
    });
    return byDate;
  });
  const last: Array<number | null> = series.map(() => null);
  return dates.map((date) => {
    const row: ChartRow = { date };
    series.forEach((item, index) => {
      const value = maps[index].get(date);
      if (value !== undefined) last[index] = value;
      row[item.id] = last[index];
    });
    return row;
  });
}

interface BrushRange {
  startIndex?: number;
  endIndex?: number;
}

export function PerformanceChart({
  dates,
  series,
}: {
  dates: string[];
  series: PerformanceSeries[];
}) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [zoomed, setZoomed] = useState(false);
  const [brushKey, setBrushKey] = useState(0);

  const rows = useMemo(() => buildRows(dates, series), [dates, series]);

  function toggle(id: string) {
    setHidden((current) => ({ ...current, [id]: !current[id] }));
  }

  function resetZoom() {
    setBrushKey((key) => key + 1);
    setZoomed(false);
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Historical performance</h2>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            Growth of 100 with fixed weights, no costs, raw prices, in-sample. A descriptive chart,
            not a backtest.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex flex-wrap gap-2 text-xs" role="group" aria-label="Toggle a series">
            {series.map((item) => {
              const off = hidden[item.id] ?? false;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => toggle(item.id)}
                  aria-pressed={!off}
                  className={
                    off
                      ? "flex items-center gap-1 rounded-full border border-gray-300 px-2 py-0.5 text-gray-400 line-through dark:border-gray-700"
                      : "flex items-center gap-1 rounded-full border border-gray-300 px-2 py-0.5 dark:border-gray-700"
                  }
                >
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: off ? "#9ca3af" : item.color }}
                    aria-hidden
                  />
                  {item.label}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={resetZoom}
            className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400"
          >
            Reset zoom
          </button>
        </div>
      </div>

      <div
        className="mt-2"
        role="img"
        aria-label="Growth of 100 for each portfolio versus the benchmark, with a dashed baseline at 100. Drag the brush under the chart to zoom."
      >
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={AXIS_TICK}
              tickFormatter={formatDateTick}
              minTickGap={48}
              tickMargin={6}
            />
            <YAxis
              tick={AXIS_TICK}
              width={52}
              domain={["auto", "auto"]}
              tickFormatter={(value: number) => value.toFixed(0)}
              label={{
                value: "Growth of 100",
                angle: -90,
                position: "insideLeft",
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <Tooltip
              content={<PerformanceTooltip />}
              cursor={{ stroke: GRID_STROKE, strokeDasharray: "3 3" }}
            />
            <ReferenceLine y={100} stroke={GRID_STROKE} strokeDasharray="4 4" />
            {series.map((item) => (
              <Line
                key={item.id}
                type="monotone"
                dataKey={item.id}
                name={item.label}
                stroke={item.color}
                strokeWidth={1.8}
                dot={false}
                connectNulls
                isAnimationActive={false}
                hide={hidden[item.id] ?? false}
              />
            ))}
            <Brush
              key={brushKey}
              dataKey="date"
              height={22}
              travellerWidth={8}
              stroke={CHART_COLORS.frontier}
              onChange={(range: BrushRange) =>
                setZoomed((range.startIndex ?? 0) > 0 || (range.endIndex ?? 0) > 0)
              }
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        {zoomed
          ? "Zoomed view: drag the handles under the chart, or press Reset zoom."
          : "Drag the handles under the chart to zoom into a period."}
      </p>

      <div className="mt-3 overflow-x-auto">
        <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
          Summary for the full timeframe
        </p>
        <table className="w-full text-xs">
          <caption className="sr-only">
            Full-timeframe return statistics for each portfolio
          </caption>
          <thead>
            <tr className="text-left text-gray-500 dark:text-gray-400">
              <th scope="col" className="py-1 font-medium">
                Portfolio
              </th>
              <th scope="col" className="py-1 font-medium">
                Total return
              </th>
              <th scope="col" className="py-1 font-medium">
                Annualized
              </th>
              <th scope="col" className="py-1 font-medium">
                Max drawdown
              </th>
            </tr>
          </thead>
          <tbody>
            {series.map((item) => (
              <tr key={item.id}>
                <td className="py-1">
                  <span className="flex items-center gap-1">
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: item.color }}
                      aria-hidden
                    />
                    {item.label}
                  </span>
                </td>
                <td className="py-1">{formatSignedPercent(item.performance.total_return)}</td>
                <td className="py-1">{formatSignedPercent(item.performance.annualized_return)}</td>
                <td className="py-1">{formatPercent(item.performance.max_drawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

