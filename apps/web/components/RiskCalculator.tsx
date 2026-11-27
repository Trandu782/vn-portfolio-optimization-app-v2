"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { InfoTip } from "@/components/InfoTip";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { inputClass, selectClass } from "@/components/ui/Field";
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
import { PerformanceChart } from "./charts/PerformanceChart";
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
  current: "#3b82f6",
  optimized: "#4cc38a",
  equal_weight: "#e0a243",
  benchmark: "#71717a",
};

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

  useEffect(() => {
    let activeFlag = true;
    fetchDataFreshness()
      .then((freshness) => {
        if (activeFlag) setLatestDate(freshness.latest_date);
      })
      .catch(() => {
        // Fall back to today's date when freshness is unavailable.
      });
    return () => {
      activeFlag = false;
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

  runRef.current = () => {
    void handleAnalyze();
  };

  useEffect(() => {
    if (autoRanRef.current || !options || !selection) return;
    if (!currentWeights && !optimizedWeights) return;
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
    <section className="space-y-6">
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
        <p className="rounded-xl border border-dashed border-strong p-6 text-center text-sm text-fg-muted">
          {selection
            ? "Press Analyse to compare your portfolios and the market index."
            : "Build a universe on the Optimize page first, then come back here."}
        </p>
      ) : (
        <>
          <p className="text-sm leading-6 text-fg-secondary">
            Here is how each portfolio&apos;s risk compares over{" "}
            <span className="font-mono tabular-nums text-fg">
              {result.dates[0]} to {result.dates[result.dates.length - 1]}
            </span>{" "}
            against {benchmarkName(options, result.benchmark)}. Lower volatility and drawdown are
            calmer; higher Sharpe, Treynor and alpha are better.
          </p>

          {outdated && (
            <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
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
                <h2 className="text-base font-medium text-fg">Detailed risk</h2>
                <span className="text-xs text-fg-muted">{SUBJECT_LABELS[active]}</span>
              </div>
              <DetailedCharts block={activeBlock} />
            </div>
          )}
        </>
      )}
    </section>
  );
}

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
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-medium text-fg">Compare the risk</h2>
          <p className="mt-1 text-sm text-fg-secondary">
            The metric list and the benchmark options come from the API.
          </p>
        </div>
        <Button size="sm" onClick={onToggleAdvanced}>
          {showAdvanced ? "Hide advanced settings" : "Advanced settings"}
        </Button>
      </div>

      <TimeframePicker
        selection={timeframe}
        latestDate={latestDate}
        onChange={onTimeframeChange}
        copyLabel="Optimize"
        onCopyOther={onCopyTimeframe}
      />

      {showAdvanced && (
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-sm">
            <span className="block font-medium text-fg">Benchmark</span>
            <select
              value={benchmark}
              onChange={(event) => onBenchmarkChange(event.target.value)}
              className={`${selectClass} w-full`}
            >
              {(options?.benchmarks ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1.5 text-sm">
            <span className="block font-medium text-fg">Worst-day confidence (%)</span>
            <input
              type="number"
              min={1}
              max={99.9}
              step="0.1"
              value={confidencePercent}
              onChange={(event) => onConfidenceChange(event.target.value)}
              className={`${inputClass} w-full font-mono tabular-nums`}
            />
          </label>
        </div>
      )}

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-fg">Metrics to compute</legend>
        <div className="grid gap-2.5 sm:grid-cols-2">
          {metricOptions.map((metric) => (
            <label key={metric.id} className="flex cursor-pointer items-start gap-2.5 text-xs">
              <input
                type="checkbox"
                checked={selected[metric.id] ?? false}
                onChange={() => onToggleMetric(metric.id)}
                className="mt-0.5 h-4 w-4 accent-accent"
              />
              <span>
                <span className="font-medium text-fg">{metric.name}</span>
                <span className="mt-0.5 block text-fg-muted">{plainHelp(metric)}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={onAnalyze}
          disabled={loading || !options || selectedCount === 0 || !hasUniverse}
        >
          {loading ? "Analysing\u2026" : "Analyse"}
        </Button>
        {options && (
          <span className="font-mono text-xs tabular-nums text-fg-muted">
            {selectedCount} of {metricOptions.length} metrics
          </span>
        )}
      </div>

      {error && <p className="text-sm text-warn">{error}</p>}
    </Card>
  );
}

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
  const cols =
    subjects.length === 3
      ? "grid-cols-1 md:grid-cols-3"
      : "grid-cols-1 md:grid-cols-2 xl:grid-cols-4";
  return (
    <div className={`grid gap-4 ${cols}`}>
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
      className={`flex flex-col justify-between space-y-3 rounded-xl border bg-surface p-4 transition-colors duration-150 ease-unslop ${
        active
          ? "border-accent shadow-[inset_0_2px_0_0_var(--accent)]"
          : "border-hairline hover:border-strong"
      }`}
    >
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium text-fg">{SUBJECT_LABELS[id]}</h3>
            <p className="mt-0.5 text-xs text-fg-muted">{SUBJECT_HELP[id]}</p>
          </div>
          <span
            className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: SUBJECT_COLORS[id] }}
            aria-hidden="true"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          {cards.map((card) => (
            <div key={card.id} className="rounded-lg border border-hairline bg-raised/50 p-2.5">
              <div className="flex items-center gap-1 text-xs text-fg-muted">
                <span className="truncate">{card.label}</span>
                <InfoTip text={card.help} />
              </div>
              <div className="mt-1 font-mono text-base font-medium tabular-nums text-fg">
                {card.display}
              </div>
            </div>
          ))}
        </div>
      </div>

      <Button
        size="sm"
        variant={active ? "ghost" : "secondary"}
        onClick={onSelect}
        className={`w-full ${active ? "text-accent-ink" : ""}`}
      >
        {active ? "Showing details" : "Show details"}
      </Button>
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
