"use client";

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

import { Card } from "@/components/ui/Card";
import {
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
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
      <p className="font-mono font-medium text-fg">{String(label ?? "")}</p>
      <ul className="mt-1.5 space-y-1">
        {rows.map((entry) => {
          const level = entry.value as number;
          return (
            <li key={String(entry.dataKey ?? entry.name)} className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-fg-secondary">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: entry.color ?? "#71717a" }}
                  aria-hidden="true"
                />
                {String(entry.name ?? "")}
              </span>
              <span className="ml-auto font-mono tabular-nums text-fg">
                {formatLevel(level)}{" "}
                <span className="text-fg-muted">
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
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium text-fg">Historical performance</h2>
          <p className="mt-1 text-xs text-fg-muted">
            Growth of 100 with fixed weights, no costs, raw prices, in-sample. A descriptive chart,
            not a backtest.
          </p>
        </div>
        <div className="flex flex-col items-start sm:items-end gap-1.5">
          <div className="flex flex-wrap gap-1.5 text-xs" role="group" aria-label="Toggle a series">
            {series.map((item) => {
              const off = hidden[item.id] ?? false;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => toggle(item.id)}
                  aria-pressed={!off}
                  className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                    off
                      ? "border-hairline bg-surface text-fg-muted line-through"
                      : "border-hairline bg-surface text-fg-secondary hover:border-strong hover:text-fg"
                  }`}
                >
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ backgroundColor: off ? "#85858b" : item.color }}
                    aria-hidden="true"
                  />
                  {item.label}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={resetZoom}
            className="text-xs text-accent-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm"
          >
            Reset zoom
          </button>
        </div>
      </div>

      <div
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
      <p className="text-xs text-fg-muted">
        {zoomed
          ? "Zoomed view: drag the handles under the chart, or press Reset zoom."
          : "Drag the handles under the chart to zoom into a period."}
      </p>

      <div className="space-y-2">
        <p className="text-xs font-medium text-fg-secondary">
          Summary for the full timeframe
        </p>
        <div className="overflow-x-auto rounded-xl border border-hairline">
          <table className="w-full text-xs">
            <caption className="sr-only">
              Full-timeframe return statistics for each portfolio
            </caption>
            <thead>
              <tr className={tableHeaderRowClass}>
                <th scope="col" className={tableHeaderCellClass}>
                  Portfolio
                </th>
                <th scope="col" className={`${tableHeaderCellClass} text-right`}>
                  Total return
                </th>
                <th scope="col" className={`${tableHeaderCellClass} text-right`}>
                  Annualized
                </th>
                <th scope="col" className={`${tableHeaderCellClass} text-right`}>
                  Max drawdown
                </th>
              </tr>
            </thead>
            <tbody>
              {series.map((item) => (
                <tr key={item.id} className={tableRowHoverClass}>
                  <td className={`${tableBodyCellClass} text-fg`}>
                    <span className="flex items-center gap-2">
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{ backgroundColor: item.color }}
                        aria-hidden="true"
                      />
                      {item.label}
                    </span>
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {formatSignedPercent(item.performance.total_return)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {formatSignedPercent(item.performance.annualized_return)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {formatPercent(item.performance.max_drawdown)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}
