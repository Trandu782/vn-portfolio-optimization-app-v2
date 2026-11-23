"use client";

/**
 * Box plot of one ratio's sector distribution with the ticker marked
 * (docs/V2_SPEC.md section 3.3).
 *
 * A single horizontal box per ratio is clearer than a dense Recharts box plot and
 * keeps the "how to read this" story explicit: the box is the middle half of the
 * sector (Q1-Q3), the line is the median, the whiskers run to the lowest/highest
 * peer and the coloured dot marks this ticker. Every drawn element carries a
 * native tooltip, and the value axis is labelled with real values.
 */

import { AXIS_TEXT, GRID_STROKE } from "@/lib/chart-theme";
import {
  formatRatioValue,
  verdictTone,
  type BoxPlotStats,
  type RatioVerdict,
  type VerdictTone,
} from "@/lib/fundamentals";

const TONE_FILL: Record<VerdictTone, string> = {
  good: "#16a34a",
  bad: "#dc2626",
  warn: "#d97706",
  neutral: "#6b7280",
};

const VIEW_W = 640;
const VIEW_H = 150;
const PAD_X = 24;
const CENTER_Y = 66;
const BOX_H = 30;
const BOX_FILL = "#dbeafe";
const BOX_STROKE = "#2563eb";
const MEDIAN_STROKE = "#1e3a8a";
const WHISKER_STROKE = "#6b7280";

function uniqueSorted(values: number[]): number[] {
  return [...new Set(values)].sort((a, b) => a - b);
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
  const ticks = uniqueSorted([stats.min, stats.q1, stats.median, stats.q3, stats.max]);
  const tone = verdictTone(verdict);
  const markerX = tickerValue === null ? null : clampX(tickerValue);
  const axisY = CENTER_Y + BOX_H / 2 + 14;

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}: sector distribution</h3>
        <span className="text-xs text-gray-500 dark:text-gray-400">N = {n} peers</span>
      </div>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
        The box is the middle half of the sector (25th-75th percentile), the line is the
        median and the whiskers run to the lowest and highest peer. The dot is this ticker.
      </p>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="mt-2 w-full"
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
          <g key={tick}>
            <line x1={x(tick)} y1={axisY} x2={x(tick)} y2={axisY + 4} stroke={AXIS_TEXT} />
            <text
              x={x(tick)}
              y={axisY + 16}
              textAnchor="middle"
              fontSize={10}
              fill={AXIS_TEXT}
            >
              {fmt(tick)}
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
        <line x1={x(stats.min)} y1={CENTER_Y - 7} x2={x(stats.min)} y2={CENTER_Y + 7} stroke={WHISKER_STROKE} />
        <line x1={x(stats.max)} y1={CENTER_Y - 7} x2={x(stats.max)} y2={CENTER_Y + 7} stroke={WHISKER_STROKE} />

        <rect
          x={x(stats.q1)}
          y={CENTER_Y - BOX_H / 2}
          width={Math.max(1, x(stats.q3) - x(stats.q1))}
          height={BOX_H}
          rx={3}
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
              stroke="#ffffff"
              strokeWidth={2}
            >
              <title>{`This ticker ${fmt(tickerValue)}`}</title>
            </circle>
            <text
              x={markerX}
              y={CENTER_Y - BOX_H / 2 - 10}
              textAnchor="middle"
              fontSize={10}
              fontWeight={600}
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
    </div>
  );
}
