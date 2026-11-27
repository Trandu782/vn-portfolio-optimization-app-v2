"use client";

import { Card } from "@/components/ui/Card";
import { AXIS_TEXT, GRID_STROKE } from "@/lib/chart-theme";
import {
  formatRatioValue,
  verdictTone,
  type BoxPlotStats,
  type RatioVerdict,
  type VerdictTone,
} from "@/lib/fundamentals";

const TONE_FILL: Record<VerdictTone, string> = {
  good: "#4cc38a",
  bad: "#e5484d",
  warn: "#e0a243",
  neutral: "#71717a",
};

const VIEW_W = 640;
const VIEW_H = 164;
const PAD_X = 28;
const CENTER_Y = 64;
const BOX_H = 30;
const BOX_FILL = "rgba(59, 130, 246, 0.16)";
const BOX_STROKE = "#3b82f6";
const MEDIAN_STROKE = "#60a5fa";
const WHISKER_STROKE = "#85858b";
const MIN_TICK_GAP = 48;

interface TickEntry {
  value: number;
  xPos: number;
  priority: number;
  row: 0 | 1;
}

function layoutTicks(stats: BoxPlotStats, x: (value: number) => number): TickEntry[] {
  const candidates: Array<{ value: number; priority: number }> = [
    { value: stats.median, priority: 3 },
    { value: stats.min, priority: 2 },
    { value: stats.max, priority: 2 },
    { value: stats.q1, priority: 1 },
    { value: stats.q3, priority: 1 },
  ];

  // Deduplicate by exact value, keeping highest priority.
  const byValue = new Map<number, number>();
  for (const item of candidates) {
    const prev = byValue.get(item.value) ?? 0;
    if (item.priority > prev) byValue.set(item.value, item.priority);
  }

  const sorted = [...byValue.entries()]
    .map(([value, priority]) => ({ value, xPos: x(value), priority, row: 0 as 0 | 1 }))
    .sort((a, b) => a.xPos - b.xPos);

  const row0Xs: number[] = [];
  const row1Xs: number[] = [];
  const placed: TickEntry[] = [];

  // Place higher-priority ticks first so median/min/max win row 0.
  const byPriority = [...sorted].sort((a, b) => b.priority - a.priority);
  for (const item of byPriority) {
    const fitsRow0 = row0Xs.every((other) => Math.abs(other - item.xPos) >= MIN_TICK_GAP);
    if (fitsRow0) {
      row0Xs.push(item.xPos);
      placed.push({ ...item, row: 0 });
      continue;
    }
    const fitsRow1 = row1Xs.every((other) => Math.abs(other - item.xPos) >= MIN_TICK_GAP);
    if (fitsRow1) {
      row1Xs.push(item.xPos);
      placed.push({ ...item, row: 1 });
    }
  }

  return placed.sort((a, b) => a.xPos - b.xPos);
}

export function RatioBoxPlot({
  label,
  stats,
  tickerValue,
  isPercentage,
  verdict,
  n,
}: {
  label: string;
  stats: BoxPlotStats;
  tickerValue: number | null;
  isPercentage: boolean;
  verdict: RatioVerdict;
  n: number;
}) {
  const fmt = (value: number) => formatRatioValue(value, isPercentage);
  const domainLow = Math.min(stats.min, tickerValue ?? stats.min);
  const domainHigh = Math.max(stats.max, tickerValue ?? stats.max);
  const span = domainHigh - domainLow;
  const pad = span === 0 ? Math.max(Math.abs(domainHigh), 1) * 0.1 : span * 0.08;
  const low = domainLow - pad;
  const high = domainHigh + pad;
  const innerW = VIEW_W - PAD_X * 2;
  const x = (value: number) => PAD_X + ((value - low) / (high - low)) * innerW;
  const clampX = (value: number) => Math.min(PAD_X + innerW, Math.max(PAD_X, x(value)));
  const ticks = layoutTicks(stats, x);
  const tone = verdictTone(verdict);
  const markerX = tickerValue === null ? null : clampX(tickerValue);
  const axisY = CENTER_Y + BOX_H / 2 + 14;

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-fg">{label}: sector distribution</h3>
        <span className="font-mono text-xs tabular-nums text-fg-muted">N = {n} peers</span>
      </div>
      <p className="text-xs text-fg-muted">
        The box is the middle half of the sector (25th-75th percentile), the line is the
        median and the whiskers run to the lowest and highest peer. The dot is this ticker.
      </p>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="w-full"
        role="img"
        aria-label={`${label} sector distribution box plot with this ticker marked`}
      >
        <line
          x1={PAD_X}
          y1={axisY}
          x2={VIEW_W - PAD_X}
          y2={axisY}
          stroke={GRID_STROKE}
        />
        {ticks.map((tick) => (
          <g key={tick.value}>
            <line
              x1={tick.xPos}
              y1={axisY}
              x2={tick.xPos}
              y2={axisY + (tick.row === 1 ? 16 : 4)}
              stroke={AXIS_TEXT}
              strokeOpacity={tick.row === 1 ? 0.5 : 1}
            />
            <text
              x={tick.xPos}
              y={axisY + (tick.row === 1 ? 28 : 16)}
              textAnchor="middle"
              fontSize={10}
              fontFamily="var(--font-mono)"
              fill={AXIS_TEXT}
            >
              {fmt(tick.value)}
            </text>
          </g>
        ))}

        <line
          x1={x(stats.min)}
          y1={CENTER_Y}
          x2={x(stats.q1)}
          y2={CENTER_Y}
          stroke={WHISKER_STROKE}
          strokeDasharray="4 3"
        >
          <title>{`Lowest ${fmt(stats.min)} to 25th percentile ${fmt(stats.q1)}`}</title>
        </line>
        <line
          x1={x(stats.q3)}
          y1={CENTER_Y}
          x2={x(stats.max)}
          y2={CENTER_Y}
          stroke={WHISKER_STROKE}
          strokeDasharray="4 3"
        >
          <title>{`75th percentile ${fmt(stats.q3)} to highest ${fmt(stats.max)}`}</title>
        </line>
        <line
          x1={x(stats.min)}
          y1={CENTER_Y - 7}
          x2={x(stats.min)}
          y2={CENTER_Y + 7}
          stroke={WHISKER_STROKE}
        />
        <line
          x1={x(stats.max)}
          y1={CENTER_Y - 7}
          x2={x(stats.max)}
          y2={CENTER_Y + 7}
          stroke={WHISKER_STROKE}
        />

        <rect
          x={x(stats.q1)}
          y={CENTER_Y - BOX_H / 2}
          width={Math.max(1, x(stats.q3) - x(stats.q1))}
          height={BOX_H}
          rx={4}
          fill={BOX_FILL}
          stroke={BOX_STROKE}
        >
          <title>{`25th ${fmt(stats.q1)} · median ${fmt(stats.median)} · 75th ${fmt(stats.q3)}`}</title>
        </rect>
        <line
          x1={x(stats.median)}
          y1={CENTER_Y - BOX_H / 2}
          x2={x(stats.median)}
          y2={CENTER_Y + BOX_H / 2}
          stroke={MEDIAN_STROKE}
          strokeWidth={2}
        >
          <title>{`Sector median ${fmt(stats.median)}`}</title>
        </line>

        {markerX !== null && tickerValue !== null && (
          <g>
            <circle
              cx={markerX}
              cy={CENTER_Y}
              r={6}
              fill={TONE_FILL[tone]}
              stroke="var(--bg-surface)"
              strokeWidth={2}
            >
              <title>{`This ticker ${fmt(tickerValue)}`}</title>
            </circle>
            <text
              x={markerX}
              y={CENTER_Y - BOX_H / 2 - 10}
              textAnchor="middle"
              fontSize={11}
              fontFamily="var(--font-mono)"
              fontWeight={500}
              fill={TONE_FILL[tone]}
            >
              {`Ticker ${fmt(tickerValue)}`}
            </text>
          </g>
        )}

        <text
          x={PAD_X + innerW / 2}
          y={VIEW_H - 6}
          textAnchor="middle"
          fontSize={10}
          fill={AXIS_TEXT}
        >
          Ratio value
        </text>
      </svg>

      <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-hairline pt-2.5 font-mono text-xs tabular-nums text-fg-secondary">
        <span>Min {fmt(stats.min)}</span>
        <span>Q1 {fmt(stats.q1)}</span>
        <span className="font-medium text-fg">Median {fmt(stats.median)}</span>
        <span>Q3 {fmt(stats.q3)}</span>
        <span>Max {fmt(stats.max)}</span>
      </div>
    </Card>
  );
}
