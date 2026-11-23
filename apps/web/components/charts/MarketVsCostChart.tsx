"use client";

/** Market value versus cost basis per stock, with a VND axis. */

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

import type { PnLHolding } from "@/lib/api";
import { AXIS_TICK, GRID_STROKE, formatCompactVnd } from "@/lib/chart-theme";
import { formatVnd } from "@/lib/format";

import { TooltipBox } from "./TooltipBox";

interface ValueRow {
  symbol: string;
  market_value: number;
  cost: number;
}

interface TooltipEntry {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string;
  color?: string;
}

function ValueTooltip({
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
              {formatVnd(typeof entry.value === "number" ? entry.value : Number(entry.value ?? 0))}
            </span>
          </li>
        ))}
      </ul>
    </TooltipBox>
  );
}

export function MarketVsCostChart({ holdings }: { holdings: PnLHolding[] }) {
  const rows: ValueRow[] = holdings
    .filter((holding) => holding.cost_basis !== null)
    .map((holding) => ({
      symbol: holding.symbol,
      market_value: holding.market_value,
      cost: holding.cost_basis ?? 0,
    }));
  if (rows.length === 0) {
    return null;
  }
  return (
    <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <h2 className="text-sm font-semibold">Market value vs cost</h2>
      <div
        className="mt-2"
        role="img"
        aria-label="Market value compared with cost basis per stock, in VND."
      >
        <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 34)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid horizontal={false} stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis type="number" tick={AXIS_TICK} tickFormatter={formatCompactVnd} tickCount={5} />
            <YAxis type="category" dataKey="symbol" tick={AXIS_TICK} width={56} />
            <Tooltip content={<ValueTooltip />} cursor={{ fill: "rgba(107,114,128,0.08)" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="market_value" name="Market value" fill="#2563eb" isAnimationActive={false} />
            <Bar dataKey="cost" name="Cost" fill="#9ca3af" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">Values in VND.</p>
    </div>
  );
}
