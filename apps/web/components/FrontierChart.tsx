"use client";

/**
 * Efficient-frontier chart.
 *
 * A Recharts scatter chart with the random portfolio cloud, the exact frontier
 * line, the capital allocation line and the labelled special portfolios. It
 * supports hover tooltips (volatility, return, Sharpe and weights), clicking a
 * frontier point to move the risk slider, a highlighted marker for the selected
 * point and chips that show/hide the cloud and the capital line.
 */

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import type { FrontierResult } from "@/lib/api";
import {
  AXIS_TEXT,
  AXIS_TICK,
  CHART_COLORS,
  GRID_STROKE,
  formatAxisPercent,
  formatPercent,
} from "@/lib/chart-theme";

import { TooltipBox } from "./charts/TooltipBox";

type SpecialKind = "tangency" | "min_variance" | "equal_weight" | "current";

interface ChartPoint {
  kind: "frontier" | "cloud" | SpecialKind;
  volatility: number;
  expected_return: number;
  sharpe: number;
  weights?: Record<string, number>;
  label?: string;
  fill?: string;
  originalIndex?: number;
}

interface ShapeProps {
  cx?: number;
  cy?: number;
  payload?: ChartPoint;
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ payload?: ChartPoint }>;
  symbols: string[];
}

function pointTitle(point: ChartPoint): string {
  if (point.label) return point.label;
  if (point.kind === "cloud") return "Random mix";
  if (point.kind === "frontier") return "Frontier point";
  return point.kind;
}

function FrontierTooltip({ active, payload, symbols }: TooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload
    .map((entry) => entry.payload)
    .find((item): item is ChartPoint => item !== undefined && item.kind !== undefined);
  if (!point) return null;
  const weights = point.weights ?? {};
  const held = symbols.filter((symbol) => (weights[symbol] ?? 0) > 0);
  return (
    <TooltipBox>
      <p className="font-medium">{pointTitle(point)}</p>
      <p className="tabular-nums">Yearly volatility {formatPercent(point.volatility)}</p>
      <p className="tabular-nums">Yearly return {formatPercent(point.expected_return)}</p>
      <p className="tabular-nums">
        Sharpe {Number.isFinite(point.sharpe) ? point.sharpe.toFixed(2) : "\u2014"}
      </p>
      {held.length > 0 && (
        <ul className="mt-1 space-y-0.5 border-t border-gray-200 pt-1 dark:border-gray-700">
          {held.map((symbol) => (
            <li key={symbol} className="flex justify-between gap-3">
              <span>{symbol}</span>
              <span className="tabular-nums">{formatPercent(weights[symbol] ?? 0)}</span>
            </li>
          ))}
        </ul>
      )}
    </TooltipBox>
  );
}

function frontierShape(onSelect: (index: number) => void, selectedIndex: number) {
  return function FrontierDot(props: ShapeProps) {
    const { cx, cy, payload } = props;
    if (cx === undefined || cy === undefined || !payload || payload.originalIndex === undefined) {
      return null;
    }
    const index = payload.originalIndex;
    const isSelected = index === selectedIndex;
    return (
      <circle
        cx={cx}
        cy={cy}
        r={isSelected ? 6 : 2.5}
        fill={isSelected ? CHART_COLORS.selected : CHART_COLORS.frontier}
        stroke="#ffffff"
        strokeWidth={isSelected ? 2 : 0.5}
        style={{ cursor: "pointer" }}
        onClick={() => onSelect(index)}
      />
    );
  };
}

function specialShape(props: ShapeProps) {
  const { cx, cy, payload } = props;
  if (cx === undefined || cy === undefined || !payload) return null;
  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={5}
        fill={payload.fill ?? CHART_COLORS.equalWeight}
        stroke="#ffffff"
        strokeWidth={1}
      />
      <text x={cx + 7} y={cy - 7} fontSize={10} fill={AXIS_TEXT}>
        {payload.label}
      </text>
    </g>
  );
}

export function FrontierChart({
  result,
  selectedIndex,
  onSelect,
}: {
  result: FrontierResult;
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const [showCloud, setShowCloud] = useState(true);
  const [showCapital, setShowCapital] = useState(true);

  const layout = useMemo(() => {
    const frontierPoints: ChartPoint[] = result.frontier
      .map((point, index) => ({
        kind: "frontier" as const,
        originalIndex: index,
        volatility: point.volatility,
        expected_return: point.expected_return,
        sharpe: point.sharpe,
        weights: point.weights,
      }))
      .sort((a, b) => a.volatility - b.volatility);

    const step = Math.max(1, Math.ceil(result.random_cloud.length / 1200));
    const cloudPoints: ChartPoint[] = result.random_cloud
      .filter((_, index) => index % step === 0)
      .map((point) => ({
        kind: "cloud" as const,
        volatility: point.volatility,
        expected_return: point.expected_return,
        sharpe: point.sharpe,
      }));

    const specials: ChartPoint[] = [
      { kind: "min_variance", label: "Min variance", fill: CHART_COLORS.minVariance, ...result.min_variance },
      { kind: "tangency", label: "Max Sharpe", fill: CHART_COLORS.tangency, ...result.tangency },
      { kind: "equal_weight", label: "Equal weight", fill: CHART_COLORS.equalWeight, ...result.equal_weight },
    ];
    if (result.current) {
      specials.push({ kind: "current", label: "Your portfolio", fill: CHART_COLORS.current, ...result.current });
    }

    const vols = [0, ...frontierPoints.map((point) => point.volatility), ...cloudPoints.map((point) => point.volatility)];
    const rets = [result.risk_free_rate, ...frontierPoints.map((point) => point.expected_return), ...cloudPoints.map((point) => point.expected_return)];
    const maxVol = Math.max(...vols, 0.01) * 1.05;
    const retMin = Math.min(...rets);
    const retMax = Math.max(...rets);
    const retSpan = retMax - retMin || 0.01;
    const minRet = retMin - retSpan * 0.08;
    const maxRet = retMax + retSpan * 0.08;

    const tangency = result.tangency;
    const slope =
      tangency.volatility > 0
        ? (tangency.expected_return - result.risk_free_rate) / tangency.volatility
        : 0;
    const calEndReturn = result.risk_free_rate + slope * maxVol;

    return { frontierPoints, cloudPoints, specials, maxVol, minRet, maxRet, calEndReturn };
  }, [result]);

  const selected = result.frontier[Math.min(selectedIndex, result.frontier.length - 1)];

  return (
    <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Risk and return</h3>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {result.random_cloud.length.toLocaleString()} random mixes &middot; {result.frontier.length}{" "}
          frontier points
        </span>
      </div>

      <div
        className="mt-2 flex flex-wrap gap-2 text-xs"
        role="group"
        aria-label="Show or hide chart layers"
      >
        <button
          type="button"
          onClick={() => setShowCloud((value) => !value)}
          aria-pressed={showCloud}
          className={
            showCloud
              ? "rounded-full border border-gray-300 bg-gray-100 px-2 py-0.5 dark:border-gray-700 dark:bg-gray-800"
              : "rounded-full border border-gray-300 px-2 py-0.5 text-gray-400 dark:border-gray-700"
          }
        >
          Random mixes
        </button>
        <button
          type="button"
          onClick={() => setShowCapital((value) => !value)}
          aria-pressed={showCapital}
          className={
            showCapital
              ? "rounded-full border border-gray-300 bg-gray-100 px-2 py-0.5 dark:border-gray-700 dark:bg-gray-800"
              : "rounded-full border border-gray-300 px-2 py-0.5 text-gray-400 dark:border-gray-700"
          }
        >
          Capital line
        </button>
      </div>

      <div
        className="mt-2"
        role="img"
        aria-label="Efficient frontier: yearly volatility (risk) on the horizontal axis, yearly return on the vertical axis, with random portfolios, minimum-variance, maximum-Sharpe, equal-weight and your current portfolio."
      >
        <ResponsiveContainer width="100%" height={360}>
          <ScatterChart margin={{ top: 8, right: 20, bottom: 28, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="volatility"
              name="Volatility"
              domain={[0, layout.maxVol]}
              tickFormatter={formatAxisPercent}
              tick={AXIS_TICK}
              tickCount={6}
              tickMargin={6}
              label={{
                value: "Yearly volatility (risk) \u2192",
                position: "insideBottom",
                offset: -16,
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <YAxis
              type="number"
              dataKey="expected_return"
              name="Return"
              domain={[layout.minRet, layout.maxRet]}
              tickFormatter={formatAxisPercent}
              tick={AXIS_TICK}
              tickCount={6}
              width={52}
              label={{
                value: "Yearly return \u2192",
                angle: -90,
                position: "insideLeft",
                fill: AXIS_TEXT,
                fontSize: 11,
              }}
            />
            <ZAxis range={[6, 6]} />
            <Tooltip
              cursor={{ stroke: GRID_STROKE, strokeDasharray: "3 3" }}
              content={<FrontierTooltip symbols={result.symbols} />}
            />
            {showCloud && (
              <Scatter
                data={layout.cloudPoints}
                fill={CHART_COLORS.cloud}
                fillOpacity={0.35}
                isAnimationActive={false}
              />
            )}
            <Scatter
              data={layout.frontierPoints}
              line={{ stroke: CHART_COLORS.frontier, strokeWidth: 2 }}
              shape={frontierShape(onSelect, Math.min(selectedIndex, result.frontier.length - 1))}
              isAnimationActive={false}
            />
            <Scatter data={layout.specials} shape={specialShape} isAnimationActive={false} />
            {showCapital && (
              <ReferenceLine
                segment={[
                  { x: 0, y: result.risk_free_rate },
                  { x: layout.maxVol, y: layout.calEndReturn },
                ]}
                stroke={CHART_COLORS.capitalLine}
                strokeDasharray="4 3"
                strokeWidth={1.2}
              />
            )}
            {selected && (
              <ReferenceDot
                x={selected.volatility}
                y={selected.expected_return}
                r={7}
                fill={CHART_COLORS.selected}
                stroke="#ffffff"
                strokeWidth={2}
              />
            )}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        Each grey dot is a random mix of the same stocks. The blue line is the best return you can
        get for each level of risk; the dashed line connects cash to the best mix. Click a point on
        the blue line to load that mix.
      </p>
    </div>
  );
}


