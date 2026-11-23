"use client";

/**
 * Optional risk/return-versus-beta scatter (docs/V2_SPEC.md section 3.2).
 *
 * One point per published sector: beta on the x-axis, period return on the y-axis. Each
 * point is coloured like the sector's line in the movement chart and labelled with the
 * sector name, so the two charts read together; hovering keeps the exact numbers.
 */

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

import {
  AXIS_TEXT,
  AXIS_TICK,
  GRID_STROKE,
  formatAxisPercent,
  formatSignedPercent,
} from "@/lib/chart-theme";
import type { SectorRow } from "@/lib/sector-analysis";

import { TooltipBox } from "./TooltipBox";

const DEFAULT_POINT_COLOR = "#2563eb";

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
      <p className="font-medium">{point.name}</p>
      <p className="tabular-nums">Beta {point.beta?.toFixed(2)}</p>
      <p className="tabular-nums">Return {formatSignedPercent((point.periodReturn ?? 0) / 100)}</p>
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
      fill: colorBySector.get(row.name) ?? DEFAULT_POINT_COLOR,
    }));

  if (points.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <h2 className="text-lg font-semibold">Return versus beta</h2>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
        Each point is a sector, coloured like its line above: the further right, the more it
        moves with the benchmark; the higher, the more it returned over the window. Hover a
        point for the exact numbers.
      </p>
      <div className="mt-2" role="img" aria-label="Sector period return against beta.">
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="beta"
              name="Beta"
              tick={AXIS_TICK}
              tickFormatter={(value: number) => value.toFixed(1)}
              label={{ value: "Beta vs benchmark", position: "insideBottom", offset: -4, fill: AXIS_TEXT, fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="periodReturn"
              name="Period return"
              tick={AXIS_TICK}
              width={56}
              tickFormatter={(value: number) => formatAxisPercent(value / 100)}
              label={{ value: "Period return", angle: -90, position: "insideLeft", fill: AXIS_TEXT, fontSize: 11 }}
            />
            <Tooltip content={<ScatterTooltip />} cursor={{ stroke: GRID_STROKE, strokeDasharray: "3 3" }} />
            {points.map((point) => (
              <Scatter key={point.name} data={[point]} fill={point.fill} isAnimationActive={false}>
                <LabelList dataKey="name" position="top" style={{ fontSize: 10, fill: AXIS_TEXT }} />
              </Scatter>
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
