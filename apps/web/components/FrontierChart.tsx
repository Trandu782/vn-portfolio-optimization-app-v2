"use client";

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

import { Card } from "@/components/ui/Card";
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

function cloudLabel(result: FrontierResult): string {
  const plotted = result.assumptions.portfolios_plotted;
  const generated = result.assumptions.portfolios_generated;
  if (plotted < generated) {
    return `showing ${plotted.toLocaleString("en-US")} of ${generated.toLocaleString("en-US")} random mixes`;
  }
  return `${generated.toLocaleString("en-US")} random mixes`;
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
      <p className="font-medium text-fg">{pointTitle(point)}</p>
      <p className="mt-1 font-mono tabular-nums text-fg-secondary">
        Volatility {formatPercent(point.volatility)}
      </p>
      <p className="font-mono tabular-nums text-fg-secondary">
        Return {formatPercent(point.expected_return)}
      </p>
      <p className="font-mono tabular-nums text-fg-secondary">
        Sharpe {Number.isFinite(point.sharpe) ? point.sharpe.toFixed(2) : "\u2014"}
      </p>
      {held.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 border-t border-hairline pt-1.5 font-mono">
          {held.map((symbol) => (
            <li key={symbol} className="flex justify-between gap-4">
              <span className="text-fg">{symbol}</span>
              <span className="tabular-nums text-fg-secondary">
                {formatPercent(weights[symbol] ?? 0)}
              </span>
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
        stroke="var(--bg-surface)"
        strokeWidth={isSelected ? 2 : 0.75}
        style={{ cursor: "pointer" }}
        onClick={() => onSelect(index)}
      />
    );
  };
}

const LABEL_OFFSETS: Record<SpecialKind, { dx: number; dy: number; anchor: "start" | "end" }> = {
  min_variance: { dx: -8, dy: 4, anchor: "end" },
  tangency: { dx: 8, dy: -8, anchor: "start" },
  equal_weight: { dx: 8, dy: 12, anchor: "start" },
  current: { dx: -8, dy: -8, anchor: "end" },
};

function specialShape(props: ShapeProps) {
  const { cx, cy, payload } = props;
  if (cx === undefined || cy === undefined || !payload) return null;
  const offset =
    payload.kind in LABEL_OFFSETS
      ? LABEL_OFFSETS[payload.kind as SpecialKind]
      : { dx: 8, dy: -6, anchor: "start" as const };
  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={5}
        fill={payload.fill ?? CHART_COLORS.equalWeight}
        stroke="var(--bg-surface)"
        strokeWidth={1.5}
      />
      <text
        x={cx + offset.dx}
        y={cy + offset.dy}
        textAnchor={offset.anchor}
        fontSize={11}
        fontWeight={500}
        fill="currentColor"
        stroke="var(--bg-surface)"
        strokeWidth={3.5}
        paintOrder="stroke"
        className="text-fg"
      >
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
      {
        kind: "min_variance",
        label: "Min variance",
        fill: CHART_COLORS.minVariance,
        ...result.min_variance,
      },
      {
        kind: "tangency",
        label: "Max Sharpe",
        fill: CHART_COLORS.tangency,
        ...result.tangency,
      },
      {
        kind: "equal_weight",
        label: "Equal weight",
        fill: CHART_COLORS.equalWeight,
        ...result.equal_weight,
      },
    ];
    if (result.current) {
      specials.push({
        kind: "current",
        label: "Your portfolio",
        fill: CHART_COLORS.current,
        ...result.current,
      });
    }

    const vols = [
      ...frontierPoints.map((point) => point.volatility),
      ...cloudPoints.map((point) => point.volatility),
      ...specials.map((point) => point.volatility),
    ];
    const rets = [
      ...frontierPoints.map((point) => point.expected_return),
      ...cloudPoints.map((point) => point.expected_return),
      ...specials.map((point) => point.expected_return),
    ];

    const rawMinVol = Math.min(...vols);
    const rawMaxVol = Math.max(...vols, rawMinVol + 0.01);
    const volSpan = rawMaxVol - rawMinVol || 0.02;
    const minVol = Math.max(0, rawMinVol - volSpan * 0.14);
    const maxVol = rawMaxVol + volSpan * 0.14;

    const rawMinRet = Math.min(...rets);
    const rawMaxRet = Math.max(...rets, rawMinRet + 0.01);
    const retSpan = rawMaxRet - rawMinRet || 0.02;
    const minRet = rawMinRet - retSpan * 0.12;
    const maxRet = rawMaxRet + retSpan * 0.12;

    const tangency = result.tangency;
    const slope =
      tangency.volatility > 0
        ? (tangency.expected_return - result.risk_free_rate) / tangency.volatility
        : 0;
    const calStartReturn = result.risk_free_rate + slope * minVol;
    const calEndReturn = result.risk_free_rate + slope * maxVol;

    return {
      frontierPoints,
      cloudPoints,
      specials,
      minVol,
      maxVol,
      minRet,
      maxRet,
      calStartReturn,
      calEndReturn,
    };
  }, [result]);

  const selected = result.frontier[Math.min(selectedIndex, result.frontier.length - 1)];

  return (
    <Card compact className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-fg">Risk and return</h3>
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          {cloudLabel(result)} &middot; {result.frontier.length} frontier points
        </span>
      </div>

      <div
        className="flex flex-wrap gap-2 text-xs"
        role="group"
        aria-label="Show or hide chart layers"
      >
        <button
          type="button"
          onClick={() => setShowCloud((value) => !value)}
          aria-pressed={showCloud}
          className={`rounded-md border px-2.5 py-1 transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
            showCloud
              ? "border-strong bg-raised font-medium text-fg"
              : "border-hairline bg-surface text-fg-muted hover:text-fg"
          }`}
        >
          Random mixes
        </button>
        <button
          type="button"
          onClick={() => setShowCapital((value) => !value)}
          aria-pressed={showCapital}
          className={`rounded-md border px-2.5 py-1 transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
            showCapital
              ? "border-strong bg-raised font-medium text-fg"
              : "border-hairline bg-surface text-fg-muted hover:text-fg"
          }`}
        >
          Capital line
        </button>
      </div>

      <div
        role="img"
        aria-label="Efficient frontier: yearly volatility (risk) on the horizontal axis, yearly return on the vertical axis, with random portfolios, minimum-variance, maximum-Sharpe, equal-weight and your current portfolio."
      >
        <ResponsiveContainer width="100%" height={360}>
          <ScatterChart margin={{ top: 12, right: 24, bottom: 28, left: 8 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="volatility"
              name="Volatility"
              domain={[layout.minVol, layout.maxVol]}
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
                fillOpacity={0.32}
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
                  { x: layout.minVol, y: layout.calStartReturn },
                  { x: layout.maxVol, y: layout.calEndReturn },
                ]}
                stroke={CHART_COLORS.capitalLine}
                strokeDasharray="4 3"
                strokeWidth={1.25}
              />
            )}
            {selected && (
              <ReferenceDot
                x={selected.volatility}
                y={selected.expected_return}
                r={7}
                fill={CHART_COLORS.selected}
                stroke="var(--bg-surface)"
                strokeWidth={2}
              />
            )}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-fg-muted">
        Each grey dot is a random mix of the same stocks. The blue line is the best return you can
        get for each level of risk; the dashed line connects cash to the best mix. Click a point on
        the blue line to load that mix.
      </p>
    </Card>
  );
}
