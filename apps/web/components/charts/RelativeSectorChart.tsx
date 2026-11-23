"use client";

/**
 * Relative Sector Movement chart (docs/V2_SPEC.md section 3.2).
 *
 * Multi-line normalised return, base 0%, with the benchmark drawn as a distinct dashed
 * grey line so it never collides with a sector colour. The legend toggles each line, both
 * axes are labelled and the tooltip shows the level and the percent change from the start
 * of the window. The x-axis uses unambiguous labels: "May 2026" for normal windows and
 * "20 May" for short windows (so a one-month window does not repeat the same month).
 */

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SectorReturnPoint } from "@/lib/api";
import {
  AXIS_TEXT,
  AXIS_TICK,
  GRID_STROKE,
  formatAxisPercent,
  formatDateTick,
  formatDayMonthTick,
  formatSignedPercent,
} from "@/lib/chart-theme";
import { toggleHidden } from "@/lib/sector-analysis";

import { TooltipBox } from "./TooltipBox";

/** Distinct dashed grey for the benchmark (never one of the sector colours). */
const BENCHMARK_COLOR = "#6b7280";
/** Windows at or below this many calendar days use day + month axis labels. */
const SHORT_WINDOW_DAYS = 92;

export interface RelativeSectorSeries {
  id: string;
  label: string;
  color: string;
  points: SectorReturnPoint[];
}

interface TooltipEntry {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string | Array<number | string>;
  color?: string;
}

function ChartTooltip({
  active,
  label,
  payload,
}: {
  active?: boolean;
  label?: string | number;
  payload?: TooltipEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const rows = payload.filter(
    (entry) => typeof entry.value === "number" && Number.isFinite(entry.value),
  );
  if (rows.length === 0) return null;
  return (
    <TooltipBox>
      <p className="font-medium">{String(label ?? "")}</p>
      <ul className="mt-1 space-y-0.5">
        {rows.map((entry) => (
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
              {formatSignedPercent((entry.value as number) / 100)}
            </span>
          </li>
        ))}
      </ul>
    </TooltipBox>
  );
}

type ChartRow = Record<string, string | number>;

export function RelativeSectorChart({
  benchmarkLabel,
  benchmarkPoints,
  series,
  windowLabel,
}: {
  benchmarkLabel: string;
  benchmarkPoints: SectorReturnPoint[];
  series: RelativeSectorSeries[];
  windowLabel: string;
}) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({});

  const rows = useMemo(() => {
    const byDate = new Map<string, ChartRow>();
    const ensure = (date: string): ChartRow => {
      const existing = byDate.get(date);
      if (existing) return existing;
      const row: ChartRow = { date };
      byDate.set(date, row);
      return row;
    };
    for (const point of benchmarkPoints) ensure(point.date).benchmark = point.value;
    for (const line of series) {
      for (const point of line.points) ensure(point.date)[line.id] = point.value;
    }
    return [...byDate.values()].sort((a, b) =>
      String(a.date).localeCompare(String(b.date)),
    );
  }, [benchmarkPoints, series]);

  const isShortWindow = useMemo(() => {
    if (rows.length < 2) return false;
    const first = Date.parse(String(rows[0].date));
    const last = Date.parse(String(rows[rows.length - 1].date));
    if (!Number.isFinite(first) || !Number.isFinite(last)) return false;
    return (last - first) / (1000 * 60 * 60 * 24) <= SHORT_WINDOW_DAYS;
  }, [rows]);

  const legend = [
    { id: "benchmark", label: benchmarkLabel, color: BENCHMARK_COLOR },
    ...series.map((line) => ({ id: line.id, label: line.label, color: line.color })),
  ];


  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <h2 className="text-lg font-semibold">Relative sector movement</h2>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
        Each line is a sector index set to 0% at the start of the window ({windowLabel}).
        The dashed grey line is {benchmarkLabel}; the gap to it is the sector&apos;s relative move.
      </p>

      <div className="mt-2 flex flex-wrap gap-2 text-xs" role="group" aria-label="Toggle a sector">
        {legend.map((item) => {
          const off = hidden[item.id] ?? false;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setHidden((current) => toggleHidden(current, item.id))}
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

      <div className="mt-2" role="img" aria-label="Normalised sector returns versus the benchmark, base 0%.">
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={AXIS_TICK}
              tickFormatter={isShortWindow ? formatDayMonthTick : formatDateTick}
              minTickGap={48}
              tickMargin={6}
            />
            <YAxis
              tick={AXIS_TICK}
              width={56}
              tickFormatter={(value: number) => formatAxisPercent(value / 100)}
              label={{
                value: "Change from start",
                angle: -90,
                position: "insideLeft",
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ stroke: GRID_STROKE, strokeDasharray: "3 3" }}
            />
            <ReferenceLine y={0} stroke={GRID_STROKE} strokeDasharray="4 4" />
            <Line
              type="monotone"
              dataKey="benchmark"
              name={benchmarkLabel}
              stroke={BENCHMARK_COLOR}
              strokeWidth={2.6}
              strokeDasharray="6 4"
              dot={false}
              connectNulls
              isAnimationActive={false}
              hide={hidden.benchmark ?? false}
            />
            {series.map((line) => (
              <Line
                key={line.id}
                type="monotone"
                dataKey={line.id}
                name={line.label}
                stroke={line.color}
                strokeWidth={1.5}
                dot={false}
                connectNulls
                isAnimationActive={false}
                hide={hidden[line.id] ?? false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

