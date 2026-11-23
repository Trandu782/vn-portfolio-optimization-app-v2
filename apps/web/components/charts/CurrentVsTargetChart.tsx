"use client";

/** Current versus target weights per holding, with a percentage axis. */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { RebalanceResult } from "@/lib/api";
import { AXIS_TICK, GRID_STROKE, formatPercent } from "@/lib/chart-theme";

import { TooltipBox } from "./TooltipBox";

interface WeightRow {
  symbol: string;
  current: number;
  target: number;
}

interface TooltipEntry {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string;
  color?: string;
}

function WeightTooltip({
  active,
  label,
  payload,
}: {
  active?: boolean;
  label?: string | number;
  payload?: TooltipEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <TooltipBox>
      <p className="font-medium">{String(label ?? "")}</p>
      <ul className="mt-1 space-y-0.5">
        {payload.map((entry) => (
          <li key={String(entry.dataKey ?? entry.name)} className="flex items-center gap-2">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: entry.color ?? "#6b7280" }}
              aria-hidden
            />
            <span>{String(entry.name ?? "")}</span>
            <span className="ml-auto tabular-nums">
              {formatPercent(typeof entry.value === "number" ? entry.value : Number(entry.value ?? 0))}
            </span>
          </li>
        ))}
      </ul>
    </TooltipBox>
  );
}

export function CurrentVsTargetChart({
  positions,
  cashWeight,
  targetCashWeight,
  heaviest,
}: {
  positions: RebalanceResult["positions"];
  cashWeight: number;
  targetCashWeight: number;
  heaviest: number;
}) {
  const rows: WeightRow[] = [
    ...positions.map((item) => ({
      symbol: item.symbol,
      current: item.current_weight,
      target: item.target_weight,
    })),
    { symbol: "CASH", current: cashWeight, target: targetCashWeight },
  ];
  const domainMax = Math.max(heaviest, 0.05);
  return (
    <div
      className="space-y-1"
      role="img"
      aria-label="Current versus target portfolio weights per holding, in percent."
    >
      <ResponsiveContainer width="100%" height={Math.max(180, rows.length * 34)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={GRID_STROKE} strokeDasharray="3 3" />
          <XAxis
            type="number"
            tick={AXIS_TICK}
            tickFormatter={(value: number) => formatPercent(value, 0)}
            domain={[0, domainMax]}
            tickCount={5}
          />
          <YAxis type="category" dataKey="symbol" tick={AXIS_TICK} width={56} />
          <Tooltip content={<WeightTooltip />} cursor={{ fill: "rgba(107,114,128,0.08)" }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="current" name="Current" fill="#9ca3af" isAnimationActive={false} />
          <Bar dataKey="target" name="Target" fill="#2563eb" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-gray-500 dark:text-gray-400">Weights as a share of total value.</p>
    </div>
  );
}
