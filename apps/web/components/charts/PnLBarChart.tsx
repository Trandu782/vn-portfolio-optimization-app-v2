"use client";

/** Profit-and-loss per stock as a horizontal bar chart with a VND axis. */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { PnLHolding } from "@/lib/api";
import { AXIS_TICK, GRID_STROKE, formatCompactVnd } from "@/lib/chart-theme";
import { formatVnd } from "@/lib/format";

import { TooltipBox } from "./TooltipBox";

interface PnlRow {
  symbol: string;
  pnl: number;
  fill: string;
}

function PnlTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: PnlRow }> }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <TooltipBox>
      <p className="font-medium">{row.symbol}</p>
      <p className="tabular-nums">{formatVnd(row.pnl)}</p>
    </TooltipBox>
  );
}

export function PnLBarChart({ holdings }: { holdings: PnLHolding[] }) {
  const rows: PnlRow[] = holdings
    .filter((holding) => holding.unrealized_pnl !== null)
    .map((holding) => {
      const pnl = holding.unrealized_pnl ?? 0;
      return { symbol: holding.symbol, pnl, fill: pnl >= 0 ? "#059669" : "#dc2626" };
    });
  if (rows.length === 0) {
    return null;
  }
  return (
    <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <h2 className="text-sm font-semibold">Profit and loss by stock</h2>
      <div
        className="mt-2"
        role="img"
        aria-label="Unrealized profit and loss per stock in VND; green is profit, red is a loss."
      >
        <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 30)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid horizontal={false} stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis type="number" tick={AXIS_TICK} tickFormatter={formatCompactVnd} tickCount={5} />
            <YAxis type="category" dataKey="symbol" tick={AXIS_TICK} width={56} />
            <Tooltip content={<PnlTooltip />} cursor={{ fill: "rgba(107,114,128,0.08)" }} />
            <ReferenceLine x={0} stroke={GRID_STROKE} />
            <Bar dataKey="pnl" name="P&L" isAnimationActive={false} radius={[0, 3, 3, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        Values in VND. Green is profit, red is a loss.
      </p>
    </div>
  );
}
