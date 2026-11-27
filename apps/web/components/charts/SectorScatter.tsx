"use client";

import {
  CartesianGrid,
  LabelList,
  Scatter,
  ScatterChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui/Card";
import {
  AXIS_TEXT,
  AXIS_TICK,
  CHART_COLORS,
  GRID_STROKE,
  formatAxisPercent,
  formatSignedPercent,
} from "@/lib/chart-theme";
import type { SectorRow } from "@/lib/sector-analysis";

import { TooltipBox } from "./TooltipBox";

function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { name?: string; beta?: number; periodReturn?: number } }>;
}) {
  const point = payload?.[0]?.payload;
  if (!active || point === undefined) return null;
  return (
    <TooltipBox>
      <p className="font-medium text-fg">{point.name}</p>
      <p className="mt-1 font-mono tabular-nums text-fg-secondary">
        Beta {point.beta?.toFixed(2)}
      </p>
      <p className="font-mono tabular-nums text-fg-secondary">
        Return {formatSignedPercent((point.periodReturn ?? 0) / 100)}
      </p>
    </TooltipBox>
  );
}

export function SectorScatter({
  rows,
  colorBySector,
}: {
  rows: SectorRow[];
  colorBySector: Map<string, string>;
}) {
  const points = rows
    .filter((row) => row.status === "ok" && row.beta !== null && row.periodReturn !== null)
    .map((row) => ({
      name: row.name,
      beta: row.beta as number,
      periodReturn: row.periodReturn as number,
      fill: colorBySector.get(row.name) ?? CHART_COLORS.frontier,
    }));

  if (points.length === 0) {
    return null;
  }

  return (
    <Card className="space-y-3">
      <div>
        <h2 className="text-base font-medium text-fg">Return versus beta</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Each point is a sector, coloured like its line above: the further right, the more it
          moves with the benchmark; the higher, the more it returned over the window. Hover a
          point for the exact numbers.
        </p>
      </div>
      <div role="img" aria-label="Sector period return against beta.">
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 12, right: 20, bottom: 12, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="beta"
              name="Beta"
              tick={AXIS_TICK}
              tickFormatter={(value: number) => value.toFixed(1)}
              label={{
                value: "Beta vs benchmark",
                position: "insideBottom",
                offset: -6,
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <YAxis
              type="number"
              dataKey="periodReturn"
              name="Period return"
              tick={AXIS_TICK}
              width={56}
              tickFormatter={(value: number) => formatAxisPercent(value / 100)}
              label={{
                value: "Period return",
                angle: -90,
                position: "insideLeft",
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <Tooltip
              content={<ScatterTooltip />}
              cursor={{ stroke: GRID_STROKE, strokeDasharray: "3 3" }}
            />
            {points.map((point) => (
              <Scatter key={point.name} data={[point]} fill={point.fill} isAnimationActive={false}>
                <LabelList
                  dataKey="name"
                  position="top"
                  style={{ fontSize: 11, fill: AXIS_TEXT }}
                />
              </Scatter>
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
