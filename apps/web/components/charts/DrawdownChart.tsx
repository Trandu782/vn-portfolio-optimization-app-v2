"use client";

/**
 * Drawdown chart: the decline from the running peak, 0 at the top.
 *
 * Shows date ticks, a percent Y axis, a crosshair tooltip and a marker on the
 * worst (maximum) drawdown point so the worst moment is obvious.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DrawdownMetric } from "@/lib/api";
import {
  AXIS_TEXT,
  AXIS_TICK,
  CHART_COLORS,
  GRID_STROKE,
  formatDateTick,
  formatPercent,
} from "@/lib/chart-theme";

import { TooltipBox } from "./TooltipBox";

interface DrawdownTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: Array<{ value?: number | string }>;
}

function DrawdownTooltip({ active, label, payload }: DrawdownTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const value = payload[0]?.value;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return (
    <TooltipBox>
      <p className="font-medium">{String(label ?? "")}</p>
      <p className="tabular-nums">Drawdown {formatPercent(value)}</p>
    </TooltipBox>
  );
}

export function DrawdownChart({ metric }: { metric: DrawdownMetric }) {
  const data = metric.dates.map((date, index) => ({
    date,
    drawdown: metric.drawdown[index] ?? 0,
  }));
  if (data.length === 0) return null;

  let lowestIndex = 0;
  for (let index = 1; index < data.length; index += 1) {
    if (data[index].drawdown < data[lowestIndex].drawdown) lowestIndex = index;
  }
  const lowest = Math.min(0, data[lowestIndex]?.drawdown ?? 0);
  const worst = data[lowestIndex];

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Drawdown</h3>
        <span className="text-xs text-red-600 dark:text-red-400">
          Max {formatPercent(metric.max_drawdown)}
        </span>
      </div>
      <div
        className="mt-2"
        role="img"
        aria-label={`Drawdown from ${metric.dates[0]} to ${metric.dates[metric.dates.length - 1]}, worst ${formatPercent(metric.max_drawdown)}.`}
      >
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={AXIS_TICK}
              tickFormatter={formatDateTick}
              minTickGap={40}
              tickMargin={6}
            />
            <YAxis
              tick={AXIS_TICK}
              width={48}
              domain={[lowest, 0]}
              tickFormatter={(value: number) => formatPercent(value, 0)}
              label={{
                value: "Drawdown",
                angle: -90,
                position: "insideLeft",
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <Tooltip
              content={<DrawdownTooltip />}
              cursor={{ stroke: GRID_STROKE, strokeDasharray: "3 3" }}
            />
            <ReferenceLine y={0} stroke={GRID_STROKE} />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke={CHART_COLORS.drawdown}
              fill={CHART_COLORS.drawdown}
              fillOpacity={0.15}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            {worst && (
              <ReferenceDot
                x={worst.date}
                y={worst.drawdown}
                r={4}
                fill={CHART_COLORS.drawdown}
                stroke="#ffffff"
                strokeWidth={1}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        {data.length} observations &middot; {metric.dates[0]} to {metric.dates[metric.dates.length - 1]}
      </p>
    </div>
  );
}
