"use client";

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

import { Card } from "@/components/ui/Card";
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
      <p className="font-mono font-medium text-fg">{String(label ?? "")}</p>
      <p className="mt-1 font-mono tabular-nums text-fg-secondary">
        Drawdown {formatPercent(value)}
      </p>
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
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-fg">Drawdown</h3>
        <span className="font-mono text-xs tabular-nums text-negative">
          Max {formatPercent(metric.max_drawdown)}
        </span>
      </div>
      <div
        role="img"
        aria-label={`Drawdown from ${metric.dates[0]} to ${metric.dates[metric.dates.length - 1]}, worst ${formatPercent(metric.max_drawdown)}.`}
      >
        <ResponsiveContainer width="100%" height={240}>
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
              fillOpacity={0.14}
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
                stroke="var(--bg-surface)"
                strokeWidth={1.5}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="font-mono text-xs tabular-nums text-fg-muted">
        {data.length} observations &middot; {metric.dates[0]} to{" "}
        {metric.dates[metric.dates.length - 1]}
      </p>
    </Card>
  );
}
