"use client";

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

import { Card } from "@/components/ui/Card";
import type { PnLHolding } from "@/lib/api";
import { AXIS_TICK, CHART_COLORS, GRID_STROKE, formatCompactVnd } from "@/lib/chart-theme";
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
      <p className="font-mono font-medium text-fg">{row.symbol}</p>
      <p className="mt-0.5 font-mono tabular-nums text-fg-secondary">{formatVnd(row.pnl)}</p>
    </TooltipBox>
  );
}

export function PnLBarChart({ holdings }: { holdings: PnLHolding[] }) {
  const rows: PnlRow[] = holdings
    .filter((holding) => holding.unrealized_pnl !== null)
    .map((holding) => {
      const pnl = holding.unrealized_pnl ?? 0;
      return {
        symbol: holding.symbol,
        pnl,
        fill: pnl >= 0 ? CHART_COLORS.minVariance : CHART_COLORS.drawdown,
      };
    });
  if (rows.length === 0) {
    return null;
  }
  return (
    <Card className="space-y-3">
      <h2 className="text-sm font-medium text-fg">Profit and loss by stock</h2>
      <div
        role="img"
        aria-label="Unrealized profit and loss per stock in VND; green is profit, red is a loss."
      >
        <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 32)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid horizontal={false} stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis type="number" tick={AXIS_TICK} tickFormatter={formatCompactVnd} tickCount={5} />
            <YAxis type="category" dataKey="symbol" tick={AXIS_TICK} width={56} />
            <Tooltip content={<PnlTooltip />} cursor={{ fill: "rgba(133,133,139,0.08)" }} />
            <ReferenceLine x={0} stroke={GRID_STROKE} />
            <Bar dataKey="pnl" name="P&L" isAnimationActive={false} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-fg-muted">Values in VND. Green is profit, red is a loss.</p>
    </Card>
  );
}
