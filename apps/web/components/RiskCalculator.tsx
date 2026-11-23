"use client";

/**
 * Risk page: compare the current, optimized, equal-weight and benchmark
 * portfolios side by side.
 *
 * Every input comes from the shared store (the built universe, the evaluated
 * holdings and the chosen optimized mix). One call to `POST /api/v1/risk/compare`
 * returns the four portfolios' metrics and their historical growth series. The
 * metric list, names and descriptions come from the API registry, so a new core
 * metric appears here without a UI change.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import {
  compareRisk,
  fetchDataFreshness,
  fetchRiskOptions,
  type BetaMetric,
  type CorrelationMatrixMetric,
  type DrawdownMetric,
  type JensenAlphaMetric,
  type RiskCompareResult,
  type RiskMetricOption,
  type RiskOptions,
  type RiskPortfolioBlock,
  type SharpeMetric,
  type TreynorMetric,
  type ValueAtRiskMetric,
  type VolatilityMetric,
} from "@/lib/api";
import { useOptimize } from "@/lib/optimize-context";
import { usePortfolio } from "@/lib/portfolio-context";
import { resolveTimeframe, todayIso, validateWindow, type TimeframeSelection } from "@/lib/timeframe";
import { useTimeframes } from "@/lib/timeframe-context";
import { useUniverse } from "@/lib/universe-context";

import { CorrelationHeatmap } from "./charts/CorrelationHeatmap";
import { DrawdownChart } from "./charts/DrawdownChart";
import { PerformanceChart, type PerformanceSeries } from "./charts/PerformanceChart";
import { TimeframePicker } from "./TimeframePicker";

type SubjectId = "current" | "optimized" | "equal_weight" | "benchmark";

const SUBJECT_LABELS: Record<SubjectId, string> = {
  current: "Your current portfolio",
  optimized: "Optimized portfolio",
  equal_weight: "Equal weight",
  benchmark: "Benchmark",
};

const SUBJECT_HELP: Record<SubjectId, string> = {
  current: "The holdings you entered, measured on the shared universe.",
  optimized: "The mix you saved with \u201cUse this portfolio\u201d on the Optimize page.",
  equal_weight: "The same money split evenly across every stock in the universe.",
  benchmark: "The market index, so you can judge whether the portfolios beat it.",
};

const SUBJECT_COLORS: Record<SubjectId, string> = {
  current: "#2563eb",
  optimized: "#059669",
  equal_weight: "#d97706",
  benchmark: "#6b7280",
};

//: Plain-language help for the tooltips, keyed by metric id. The registry
//: description is the fallback for any metric not listed here.
const PLAIN_HELP: Record<string, string> = {
  annualized_volatility: "How much the value typically swings in a year. Lower is calmer.",
  sharpe: "Return earned per unit of risk. Higher is better.",
  treynor: "Return per unit of market risk (beta). Higher is better.",
  jensens_alpha: "Return above what the market predicts for this risk. Positive is good.",
  beta: "How strongly it moves with the market index. Above 1 swings more than the market.",
  max_drawdown: "The worst peak-to-trough drop over the period.",
  historical_var: "The daily loss you should only exceed on the worst 1-in-20 days.",
  correlation_matrix: "How much the stocks move together. Lower spreads the risk.",
};

export function RiskCalculator() {
  const { selection } = useUniverse();
  const { evaluation } = usePortfolio();
  const { result: optimized } = useOptimize();
  const { timeframes, setTimeframe } = useTimeframes();

  const [options, setOptions] = useState<RiskOptions | null>(null);
  const [benchmark, setBenchmark] = useState("");
  const [confidencePercent, setConfidencePercent] = useState("95");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [result, setResult] = useState<RiskCompareResult | null>(null);
  const [active, setActive] = useState<SubjectId>("current");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [latestDate, setLatestDate] = useState<string | null>(null);
  const [analyzedWindow, setAnalyzedWindow] = useState<{ start: string; end: string } | null>(null);

  const timeframe = timeframes.risk;
  const resolved = useMemo(
    () => resolveTimeframe(timeframe, latestDate ?? todayIso()),
    [timeframe, latestDate],
  );
  const windowError = useMemo(
    () => validateWindow(resolved.start, resolved.end, latestDate),
    [resolved, latestDate],
  );
  const outdated =
    analyzedWindow !== null &&
    (analyzedWindow.start !== resolved.start || analyzedWindow.end !== resolved.end);

  const autoRanRef = useRef(false);
  const runRef = useRef<() => void>(() => {});

  useEffect(() => {
    let mounted = true;
    fetchRiskOptions()
      .then((payload) => {
        if (!mounted) return;
        setOptions(payload);
        setBenchmark((current) => current || payload.defaults.benchmark);
        setConfidencePercent(String(Math.round(payload.defaults.confidence * 100)));
        const next: Record<string, boolean> = {};
        for (const metric of payload.metrics) next[metric.id] = true;
        setSelected(next);
      })
      .catch((err: unknown) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load risk options");
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  // The latest stored data date anchors every preset window.
  useEffect(() => {
    let active = true;
    fetchDataFreshness()
      .then((freshness) => {
        if (active) setLatestDate(freshness.latest_date);
      })
      .catch(() => {
        // Fall back to today's date when freshness is unavailable.
      });
    return () => {
      active = false;
    };
  }, []);

  const metricOptions = options?.metrics ?? [];
  const selectedIds = metricOptions.filter((metric) => selected[metric.id]).map((m) => m.id);
  const currentWeights = useMemo<Record<string, number> | null>(() => {
    if (!evaluation || Object.keys(evaluation.weights).length === 0) return null;
    return evaluation.weights;
  }, [evaluation]);
  const optimizedWeights = useMemo<Record<string, number> | null>(() => {
    if (!optimized || Object.keys(optimized.weights).length === 0) return null;
    return optimized.weights;
  }, [optimized]);

  async function handleAnalyze() {
    if (!selection) {
      setError("Build a universe on the Optimize page first.");
      return;
    }
    if (selectedIds.length === 0) {
      setError("Select at least one metric.");
      return;
    }
    if (!benchmark) {
      setError("Choose a benchmark to compare against.");
      return;
    }
    if (windowError) {
      setError(windowError);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await compareRisk({
        symbols: selection.symbols,
        start: resolved.start,
        end: resolved.end,
        benchmark,
        metrics: selectedIds,
        metric_params: buildMetricParams(selectedIds, fromPercentInput(confidencePercent)),
        current_weights: currentWeights,
        optimized_weights: optimizedWeights,
      });
      setResult(payload);
      setAnalyzedWindow({ start: resolved.start, end: resolved.end });
      setActive(payload.current ? "current" : payload.optimized ? "optimized" : "equal_weight");
      if (payload.warnings && payload.warnings.length > 0) {
        setError(payload.warnings.join("; "));
      }
    } catch (err: unknown) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Risk analysis failed");
    } finally {
      setLoading(false);
    }
  }

  // Keep the latest handler in a ref so the mount-time auto-run does not depend
  // on a function identity that changes every render.
  runRef.current = () => {
    void handleAnalyze();
  };

  // Rebuild automatically once when a saved universe and at least one portfolio
  // are present, so returning to the page never shows an empty result. (Step 1
  // rule.)
  useEffect(() => {
    if (autoRanRef.current || !options || !selection) return;
    if (!currentWeights && !optimizedWeights) return;
    // Wait for the latest data date so a preset resolves to the same window
    // that the freshness badge shows (a custom range does not need it).
    if (timeframe.preset !== "Custom" && !latestDate) return;
    autoRanRef.current = true;
    runRef.current();
  }, [options, selection, currentWeights, optimizedWeights, latestDate, timeframe.preset]);

  const subjects = useMemo(
    () =>
      (
        [
          { id: "current" as const, block: result?.current ?? null },
          { id: "optimized" as const, block: result?.optimized ?? null },
          { id: "equal_weight" as const, block: result?.equal_weight ?? null },
          { id: "benchmark" as const, block: result?.benchmark_portfolio ?? null },
        ] satisfies Array<{ id: SubjectId; block: RiskPortfolioBlock | null }>
      ).filter(
        (subject): subject is { id: SubjectId; block: RiskPortfolioBlock } =>
          subject.block !== null,
      ),
    [result],
  );

  const activeBlock = subjects.find((subject) => subject.id === active)?.block ?? null;

  return (
    <section className="space-y-4">
      <RiskControls
        options={options}
        benchmark={benchmark}
        onBenchmarkChange={setBenchmark}
        confidencePercent={confidencePercent}
        onConfidenceChange={setConfidencePercent}
        showAdvanced={showAdvanced}
        onToggleAdvanced={() => setShowAdvanced((value) => !value)}
        metricOptions={metricOptions}
        selected={selected}
        onToggleMetric={(id) =>
          setSelected((current) => ({ ...current, [id]: !current[id] }))
        }
        selectedCount={selectedIds.length}
        onAnalyze={() => void handleAnalyze()}
        loading={loading}
        error={error}
        hasUniverse={selection !== null}
        timeframe={timeframe}
        latestDate={latestDate}
        onTimeframeChange={(next) => setTimeframe("risk", next)}
        onCopyTimeframe={() => setTimeframe("risk", timeframes.optimize)}
      />

      {!result ? (
        <p className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
          {selection
            ? "Press Analyse to compare your portfolios and the market index."
            : "Build a universe on the Optimize page first, then come back here."}
        </p>
      ) : (
        <>
          <p className="text-sm text-gray-600 dark:text-gray-300">
            Here is how each portfolio&apos;s risk compares over {result.dates[0]} to{" "}
            {result.dates[result.dates.length - 1]} against{" "}
            {benchmarkName(options, result.benchmark)}. Lower volatility and drawdown
            are calmer; higher Sharpe, Treynor and alpha are better.
          </p>

          {outdated && (
            <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
              The timeframe changed. These results are from an earlier window; press Analyse to
              update them.
            </p>
          )}

          <ComparisonGrid
            subjects={subjects}
            options={options}
            active={active}
            onSelect={setActive}
          />

          <PerformanceChart
            dates={result.dates}
            series={subjects.map(({ id, block }) => ({
              id,
              label: SUBJECT_LABELS[id],
              color: SUBJECT_COLORS[id],
              performance: block.performance,
            }))}
          />

          {activeBlock && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">Detailed risk</h2>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {SUBJECT_LABELS[active]}
                </span>
              </div>
              <DetailedCharts block={activeBlock} />
            </div>
          )}
        </>
      )}
    </section>
  );
}

// -- controls -----------------------------------------------------------------

interface RiskControlsProps {
  options: RiskOptions | null;
  benchmark: string;
  onBenchmarkChange: (value: string) => void;
  confidencePercent: string;
  onConfidenceChange: (value: string) => void;
  showAdvanced: boolean;
  onToggleAdvanced: () => void;
  metricOptions: RiskMetricOption[];
  selected: Record<string, boolean>;
  onToggleMetric: (id: string) => void;
  selectedCount: number;
  onAnalyze: () => void;
  loading: boolean;
  error: string | null;
  hasUniverse: boolean;
  timeframe: TimeframeSelection;
  latestDate: string | null;
  onTimeframeChange: (selection: TimeframeSelection) => void;
  onCopyTimeframe: () => void;
}

function RiskControls({
  options,
  benchmark,
  onBenchmarkChange,
  confidencePercent,
  onConfidenceChange,
  showAdvanced,
  onToggleAdvanced,
  metricOptions,
  selected,
  onToggleMetric,
  selectedCount,
  onAnalyze,
  loading,
  error,
  hasUniverse,
  timeframe,
  latestDate,
  onTimeframeChange,
  onCopyTimeframe,
}: RiskControlsProps) {
  return (
    <div className="space-y-4 rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Compare the risk</h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            The metric list and the benchmark options come from the API.
          </p>
        </div>
        <button
          type="button"
          onClick={onToggleAdvanced}
          className="rounded-md border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-900"
        >
          {showAdvanced ? "Hide advanced settings" : "Advanced settings"}
        </button>
      </div>

      <TimeframePicker
        selection={timeframe}
        latestDate={latestDate}
        onChange={onTimeframeChange}
        copyLabel="Optimize"
        onCopyOther={onCopyTimeframe}
      />

      {showAdvanced && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="block font-medium">Benchmark</span>
            <select
              value={benchmark}
              onChange={(event) => onBenchmarkChange(event.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-2 py-2 dark:border-gray-700 dark:bg-gray-900"
            >
              {(options?.benchmarks ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="block font-medium">Worst-day confidence (%)</span>
            <input
              type="number"
              min={1}
              max={99.9}
              step="0.1"
              value={confidencePercent}
              onChange={(event) => onConfidenceChange(event.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-2 py-2 dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
        </div>
      )}

      <fieldset>
        <legend className="text-sm font-medium">Metrics to compute</legend>
        <div className="mt-1 grid gap-2 sm:grid-cols-2">
          {metricOptions.map((metric) => (
            <label key={metric.id} className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={selected[metric.id] ?? false}
                onChange={() => onToggleMetric(metric.id)}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">{metric.name}</span>
                <span className="mt-0.5 block text-gray-500 dark:text-gray-400">
                  {plainHelp(metric)}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onAnalyze}
          disabled={loading || !options || selectedCount === 0 || !hasUniverse}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
        >
          {loading ? "Analysing\u2026" : "Analyse"}
        </button>
        {options && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {selectedCount} of {metricOptions.length} metrics
          </span>
        )}
      </div>

      {error && <p className="text-sm text-amber-700 dark:text-amber-300">{error}</p>}
    </div>
  );
}

// -- comparison panels --------------------------------------------------------

function ComparisonGrid({
  subjects,
  options,
  active,
  onSelect,
}: {
  subjects: Array<{ id: SubjectId; block: RiskPortfolioBlock }>;
  options: RiskOptions | null;
  active: SubjectId;
  onSelect: (id: SubjectId) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {subjects.map(({ id, block }) => (
        <ComparisonPanel
          key={id}
          id={id}
          block={block}
          options={options}
          active={active === id}
          onSelect={() => onSelect(id)}
        />
      ))}
    </div>
  );
}

function ComparisonPanel({
  id,
  block,
  options,
  active,
  onSelect,
}: {
  id: SubjectId;
  block: RiskPortfolioBlock;
  options: RiskOptions | null;
  active: boolean;
  onSelect: () => void;
}) {
  const cards = scalarCards(block, options);
  return (
    <div
      className={
        active
          ? "space-y-3 rounded-lg border-2 border-blue-500 p-4"
          : "space-y-3 rounded-lg border border-gray-200 p-4 dark:border-gray-800"
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{SUBJECT_LABELS[id]}</h3>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{SUBJECT_HELP[id]}</p>
        </div>
        <span
          className="mt-1 h-3 w-3 shrink-0 rounded-full"
          style={{ backgroundColor: SUBJECT_COLORS[id] }}
          aria-hidden
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        {cards.map((card) => (
          <div key={card.id} className="rounded-md bg-gray-50 p-2 dark:bg-gray-900">
            <div className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
              <span>{card.label}</span>
              <span
                className="cursor-help text-[10px] text-gray-400"
                title={card.help}
                aria-label={card.help}
              >
                (?)
              </span>
            </div>
            <div className="text-base font-semibold">{card.display}</div>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={onSelect}
        className={
          active
            ? "w-full rounded-md bg-blue-600 px-2 py-1 text-xs text-white"
            : "w-full rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-900"
        }
      >
        {active ? "Showing details" : "Show details"}
      </button>
    </div>
  );
}

interface ScalarCard {
  id: string;
  label: string;
  display: string;
  help: string;
}

function scalarCards(block: RiskPortfolioBlock, options: RiskOptions | null): ScalarCard[] {
  const cards: ScalarCard[] = [];
  const push = (id: string, display: string) =>
    cards.push({ id, label: metricName(options, id), display, help: metricHelp(options, id) });

  const volatility = block.metrics["annualized_volatility"] as VolatilityMetric | undefined;
  if (volatility) push("annualized_volatility", formatFraction(volatility.volatility));

  const sharpe = block.metrics["sharpe"] as SharpeMetric | undefined;
  if (sharpe) push("sharpe", formatRatio(sharpe.sharpe));

  const treynor = block.metrics["treynor"] as TreynorMetric | undefined;
  if (treynor) push("treynor", formatRatio(treynor.treynor));

  const alpha = block.metrics["jensens_alpha"] as JensenAlphaMetric | undefined;
  if (alpha) push("jensens_alpha", formatSignedFraction(alpha.alpha));

  const beta = block.metrics["beta"] as BetaMetric | undefined;
  if (beta) push("beta", beta.beta.toFixed(2));

  const drawdown = block.metrics["max_drawdown"] as DrawdownMetric | undefined;
  if (drawdown) push("max_drawdown", formatFraction(drawdown.max_drawdown));

  const varMetric = block.metrics["historical_var"] as ValueAtRiskMetric | undefined;
  if (varMetric) {
    push(
      "historical_var",
      `${formatFraction(varMetric.value_at_risk)} (${(varMetric.confidence * 100).toFixed(0)}%)`,
    );
  }
  return cards;
}

function metricName(options: RiskOptions | null, id: string): string {
  return options?.metrics.find((metric) => metric.id === id)?.name ?? id;
}

function metricHelp(options: RiskOptions | null, id: string): string {
  if (PLAIN_HELP[id]) return PLAIN_HELP[id];
  return options?.metrics.find((metric) => metric.id === id)?.description ?? id;
}

function plainHelp(metric: RiskMetricOption): string {
  return PLAIN_HELP[metric.id] ?? metric.description;
}

function benchmarkName(options: RiskOptions | null, code: string): string {
  return options?.benchmarks.find((item) => item.code === code)?.name ?? code;
}

// -- detailed charts ----------------------------------------------------------

function DetailedCharts({ block }: { block: RiskPortfolioBlock }) {
  const drawdown = block.metrics["max_drawdown"] as DrawdownMetric | undefined;
  const correlation = block.metrics["correlation_matrix"] as
    | CorrelationMatrixMetric
    | undefined;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {drawdown && drawdown.drawdown.length > 0 && <DrawdownChart metric={drawdown} />}
      {correlation && correlation.matrix.length > 1 && (
        <CorrelationHeatmap metric={correlation} />
      )}
    </div>
  );
}

// -- formatting ---------------------------------------------------------------

function buildMetricParams(
  ids: string[],
  confidence: number,
): Record<string, Record<string, unknown>> {
  const params: Record<string, Record<string, unknown>> = {};
  if (ids.includes("historical_var")) params.historical_var = { confidence };
  return params;
}

function fromPercentInput(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0.95;
  return Math.min(0.999, Math.max(0.001, parsed / 100));
}

function formatFraction(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function formatSignedFraction(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "\u2014";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function formatRatio(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "\u2014";
  return value.toFixed(2);
}





