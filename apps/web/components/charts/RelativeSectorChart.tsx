"use client";

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

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
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
import {
  hideAllSectors,
  relativeChartVisibility,
  toggleHidden,
} from "@/lib/sector-analysis";

import { TooltipBox } from "./TooltipBox";

const BENCHMARK_COLOR = "#71717a";
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
      <p className="font-mono font-medium text-fg">{String(label ?? "")}</p>
      <ul className="mt-1.5 space-y-1">
        {rows.map((entry) => (
          <li key={String(entry.dataKey ?? entry.name)} className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-fg-secondary">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: entry.color ?? BENCHMARK_COLOR }}
                aria-hidden="true"
              />
              {String(entry.name ?? "")}
            </span>
            <span className="ml-auto font-mono tabular-nums text-fg">
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
  const [hoveredSector, setHoveredSector] = useState<string | null>(null);

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

  const sectorIds = useMemo(() => series.map((line) => line.id), [series]);
  const { allVisible, onlyBenchmarkVisible } = relativeChartVisibility(hidden, sectorIds);

  const legend = [
    { id: "benchmark", label: benchmarkLabel, color: BENCHMARK_COLOR },
    ...series.map((line) => ({ id: line.id, label: line.label, color: line.color })),
  ];

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium text-fg">Relative sector movement</h2>
          <p className="mt-1 text-xs text-fg-muted">
            Each line is a sector index set to 0% at the start of the window (
            <span className="font-mono tabular-nums">{windowLabel}</span>). The dashed grey line is{" "}
            {benchmarkLabel}; hover a sector chip to isolate it.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setHidden({})}
            disabled={allVisible}
            aria-label="Show all lines"
          >
            Show all
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setHidden(hideAllSectors(sectorIds))}
            disabled={onlyBenchmarkVisible}
            aria-label="Hide all sector lines"
          >
            Clear all
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 text-xs" role="group" aria-label="Toggle a sector">
        {legend.map((item) => {
          const off = hidden[item.id] ?? false;
          const isHovered = hoveredSector === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setHidden((current) => toggleHidden(current, item.id))}
              onMouseEnter={() => setHoveredSector(item.id)}
              onMouseLeave={() => setHoveredSector(null)}
              aria-pressed={!off}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                off
                  ? "border-hairline bg-surface text-fg-muted line-through"
                  : isHovered
                    ? "border-strong bg-raised font-medium text-fg"
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

      <div role="img" aria-label="Normalised sector returns versus the benchmark, base 0%.">
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
              strokeWidth={hoveredSector === "benchmark" ? 2.8 : 2.2}
              strokeOpacity={
                hoveredSector === null || hoveredSector === "benchmark" ? 1 : 0.25
              }
              strokeDasharray="6 4"
              dot={false}
              connectNulls
              isAnimationActive={false}
              hide={hidden.benchmark ?? false}
            />
            {series.map((line) => {
              const active = hoveredSector === null || hoveredSector === line.id;
              return (
                <Line
                  key={line.id}
                  type="monotone"
                  dataKey={line.id}
                  name={line.label}
                  stroke={line.color}
                  strokeWidth={hoveredSector === line.id ? 2.4 : 1.5}
                  strokeOpacity={active ? 1 : 0.2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                  hide={hidden[line.id] ?? false}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
