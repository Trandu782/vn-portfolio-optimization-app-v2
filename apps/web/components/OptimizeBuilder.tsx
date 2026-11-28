"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { InfoTip } from "@/components/InfoTip";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  inputClass,
  selectClass,
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
import { ChevronDownIcon, ChevronUpIcon, XIcon } from "@/components/ui/Icons";
import {
  buildUniverse,
  fetchDataFreshness,
  fetchOptimizeOptions,
  fetchPresetSymbols,
  fetchRiskOptions,
  fetchSymbols,
  fetchUniverseOptions,
  runFrontier,
  type FrontierPoint,
  type FrontierResult,
  type OptimizeResult,
  type ParameterSchemaProperty,
  type RiskOptions,
  type SymbolInfo,
  type UniverseBuildResponse,
  type UniverseFilterOption,
  type UniverseFilterSelection,
  type UniverseOptions,
} from "@/lib/api";
import { formatVnd, formatWeight } from "@/lib/format";
import {
  HARD_MAX_STOCKS,
  defaultMaxWeight,
  exceedsHardMax,
  feasibleMaxWeight,
  universeSizeWarnings,
} from "@/lib/optimize-guardrails";
import { useOptimize } from "@/lib/optimize-context";
import { useAppStore } from "@/lib/app-store-context";
import { usePortfolio } from "@/lib/portfolio-context";
import { resolveTimeframe, todayIso, validateWindow } from "@/lib/timeframe";
import { useTimeframes } from "@/lib/timeframe-context";
import { useUniverse } from "@/lib/universe-context";

import { FrontierChart } from "./FrontierChart";
import { OptimizeCapital, resolveCapital, type CapitalMode } from "./OptimizeCapital";
import { TickerDetailDrawer } from "./TickerDetailDrawer";
import { TimeframePicker } from "./TimeframePicker";
import { UniverseFilterPanel, type V2UniverseView } from "./UniverseFilterPanel";

const GOALS = [
  { id: "min_variance", label: "Lowest risk", detail: "Minimum variance - the steadiest mix." },
  { id: "max_sharpe", label: "Best return for the risk", detail: "Maximum Sharpe ratio." },
  { id: "equal_weight", label: "Equal split", detail: "Equal weight - an equal slice of each stock." },
] as const;

type GoalId = (typeof GOALS)[number]["id"];

const EMPTY_V2_VIEW: V2UniverseView = {
  available: false,
  sectorByTicker: {},
  warnings: [],
  flags: [],
  flagsAvailable: false,
  flagsPolicyCurrent: false,
  passing: [],
};

function propertyType(property: ParameterSchemaProperty): string {
  if (property.type) return property.type;
  for (const variant of property.anyOf ?? []) {
    if (variant.type && variant.type !== "null") return variant.type;
  }
  return "string";
}

function defaultParams(filter: UniverseFilterOption): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [name, property] of Object.entries(filter.parameter_schema?.properties ?? {})) {
    if (property.default !== undefined) {
      params[name] = property.default;
      continue;
    }
    const type = propertyType(property);
    params[name] = type === "boolean" ? false : type === "integer" || type === "number" ? 0 : "";
  }
  return params;
}

function fixedFilters(options: UniverseOptions | null): UniverseFilterSelection[] {
  if (!options) return [];
  return options.filters
    .filter((filter) => filter.id !== "exchange")
    .map((filter) => ({ id: filter.id, params: defaultParams(filter) }));
}

function frontierSentence(frontier: FrontierResult, point: FrontierPoint, goalId: string): string {
  const goal = GOALS.find((item) => item.id === goalId)?.label ?? "portfolio";
  const ranking = [...frontier.symbols].sort(
    (a, b) => (point.weights[b] ?? 0) - (point.weights[a] ?? 0),
  );
  const lead = ranking
    .slice(0, 2)
    .map((code) => `${code} at ${formatWeight(point.weights[code] ?? 0)}`)
    .join(" and ");
  return (
    `This ${goal.toLowerCase()} mix across ${frontier.symbols.length} stock(s) is led by ${lead}. ` +
    `Over the selected period it would have returned about ` +
    `${(point.expected_return * 100).toFixed(1)}% a year with about ` +
    `${(point.volatility * 100).toFixed(1)}% yearly swings (Sharpe ${point.sharpe.toFixed(2)}).`
  );
}

export function OptimizeBuilder() {
  const { selection, setSelection, clearSelection } = useUniverse();
  const { evaluation, symbols: portfolioSymbols } = usePortfolio();
  const { setResult: publishResult, clearResult } = useOptimize();
  const { timeframes, setTimeframe } = useTimeframes();
  const { v2Filter } = useAppStore();

  const portfolioSeeded = useRef(false);

  const [universeOptions, setUniverseOptions] = useState<UniverseOptions | null>(null);
  const [riskOptions, setRiskOptions] = useState<RiskOptions | null>(null);
  const [universeSymbols, setUniverseSymbols] = useState<SymbolInfo[]>([]);
  const [selected, setSelected] = useState<string[]>(
    () => selection?.selected ?? selection?.symbols ?? [],
  );
  const [search, setSearch] = useState("");
  const [universeResult, setUniverseResult] = useState<UniverseBuildResponse | null>(
    selection?.result ?? null,
  );
  const [frontier, setFrontier] = useState<FrontierResult | null>(null);
  const [frontierIndex, setFrontierIndex] = useState(0);

  const [goalId, setGoalId] = useState<GoalId>("min_variance");
  const [capitalMode, setCapitalMode] = useState<CapitalMode>("holdings");
  const [newCapital, setNewCapital] = useState("");

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [maxWeightPercent, setMaxWeightPercent] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const [varConfidence, setVarConfidence] = useState(95);
  const [numPortfolios, setNumPortfolios] = useState(5000);
  const [maxPortfolios, setMaxPortfolios] = useState<number | null>(null);
  const [seed, setSeed] = useState("");
  const [maxSectorPct, setMaxSectorPct] = useState("");
  const [maxStocks, setMaxStocks] = useState(HARD_MAX_STOCKS);
  const [v2View, setV2View] = useState<V2UniverseView>(EMPTY_V2_VIEW);

  const [presetLoading, setPresetLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [latestDate, setLatestDate] = useState<string | null>(null);
  const [ranWindow, setRanWindow] = useState<{ start: string; end: string } | null>(null);
  const [detailSymbol, setDetailSymbol] = useState<string | null>(null);

  const timeframe = timeframes.optimize;
  const resolved = useMemo(
    () => resolveTimeframe(timeframe, latestDate ?? todayIso()),
    [timeframe, latestDate],
  );
  const windowError = useMemo(
    () => validateWindow(resolved.start, resolved.end, latestDate),
    [resolved, latestDate],
  );
  const outdated =
    ranWindow !== null &&
    (ranWindow.start !== resolved.start || ranWindow.end !== resolved.end);

  useEffect(
    function () {
      if (portfolioSeeded.current || portfolioSymbols.length === 0) return;
      portfolioSeeded.current = true;
      setSelected((current) => (current.length ? current : [...portfolioSymbols]));
    },
    [portfolioSymbols],
  );

  useEffect(function () {
    let active = true;
    Promise.all([
      fetchUniverseOptions(),
      fetchSymbols(),
      fetchRiskOptions(),
      fetchDataFreshness(),
      fetchOptimizeOptions(),
    ])
      .then(function ([optionsPayload, symbolsPayload, riskPayload, freshness, optimizePayload]) {
        if (!active) return;
        setUniverseOptions(optionsPayload);
        setUniverseSymbols(symbolsPayload.symbols);
        setRiskOptions(riskPayload);
        setBenchmark((current) => current || riskPayload.defaults.benchmark);
        setLatestDate(freshness.latest_date);
        if (optimizePayload.frontier_defaults.max_stocks) {
          setMaxStocks(optimizePayload.frontier_defaults.max_stocks);
        }
        if (optimizePayload.frontier_defaults.max_portfolios) {
          setMaxPortfolios(optimizePayload.frontier_defaults.max_portfolios);
        }
      })
      .catch(function () {
        // Degrade gracefully if API is down.
      });
    return function () {
      active = false;
    };
  }, []);

  const suggestions = useMemo(
    function () {
      const query = search.trim().toUpperCase();
      if (!query) return [];
      return universeSymbols
        .filter(
          (symbol) =>
            symbol.code.includes(query) || (symbol.name ?? "").toUpperCase().includes(query),
        )
        .filter((symbol) => !selected.includes(symbol.code))
        .slice(0, 8);
    },
    [search, universeSymbols, selected],
  );

  function addSymbol(raw: string) {
    const code = raw.trim().toUpperCase();
    if (!code) return;
    setSelected((current) => (current.includes(code) ? current : [...current, code]));
    setSearch("");
  }

  function removeSymbol(code: string) {
    setSelected((current) => current.filter((item) => item !== code));
  }

  function addMany(codes: string[]) {
    setSelected((current) => {
      const next = [...current];
      for (const code of codes) {
        if (!next.includes(code)) next.push(code);
      }
      return next;
    });
  }

  function clearAllSelected() {
    setSelected([]);
    setUniverseResult(null);
    setFrontier(null);
    setRanWindow(null);
    setError(null);
    setNotice(null);
    clearSelection();
  }

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    addSymbol(search);
  }

  async function startFromVn30() {
    setError(null);
    setNotice(null);
    setPresetLoading(true);
    try {
      const response = await fetchPresetSymbols("VN30");
      setSelected(response.symbols);
      setNotice(`Loaded ${response.count} VN30 stocks`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load VN30.");
    } finally {
      setPresetLoading(false);
    }
  }

  const capital = resolveCapital(capitalMode, evaluation?.total_value ?? null, newCapital);
  const keptCount = universeResult?.symbols.length ?? 0;
  const sizeWarnings = keptCount ? universeSizeWarnings(keptCount) : [];

  const handleFind = useCallback(
    async function () {
      setError(null);
      setNotice(null);
      if (selected.length === 0) {
        setError("Add at least one stock to consider.");
        return;
      }
      if (exceedsHardMax(selected.length, maxStocks)) {
        setError(
          `At most ${maxStocks} stocks are supported. You picked ${selected.length}; remove some.`,
        );
        return;
      }
      if (capital <= 0) {
        setError("Add money to invest, or add holdings with value on the Portfolio page.");
        return;
      }
      if (windowError) {
        setError(windowError);
        return;
      }
      setRunning(true);
      clearResult();
      setFrontier(null);
      try {
        const filters = fixedFilters(universeOptions);
        const universe = await buildUniverse({
          symbols: selected,
          filters,
          start: resolved.start,
          end: resolved.end,
        });
        setUniverseResult(universe);
        setSelection({
          symbols: universe.symbols,
          selected,
          start: resolved.start,
          end: resolved.end,
          filters,
          result: universe,
        });
        if (universe.symbols.length === 0) {
          setError("No stocks passed the filters. Add more stocks or see the dropped list below.");
          return;
        }
        if (exceedsHardMax(universe.symbols.length, maxStocks)) {
          setError(
            `Filters kept ${universe.symbols.length} stocks, above the ${maxStocks} cap. Remove some stocks.`,
          );
          return;
        }
        const requestedCap =
          showAdvanced && maxWeightPercent !== ""
            ? Number(maxWeightPercent) / 100
            : defaultMaxWeight(universe.symbols.length);
        const cap = feasibleMaxWeight(universe.symbols.length, requestedCap);
        if (cap.raised) {
          setNotice(
            `Raised the max weight to ${(cap.value * 100).toFixed(0)}% so the portfolio can be fully invested`,
          );
        }
        const parsedSeed = seed.trim() === "" ? null : Number(seed);
        const requestedSectorCap =
          showAdvanced && maxSectorPct.trim() !== "" ? Number(maxSectorPct) / 100 : null;
        const sectorMap =
          Object.keys(v2View.sectorByTicker).length > 0 ? v2View.sectorByTicker : null;
        const payload = await runFrontier({
          symbols: universe.symbols,
          start: resolved.start,
          end: resolved.end,
          capital,
          max_weight: cap.value,
          max_sector_weight: requestedSectorCap,
          sectors: sectorMap,
          num_portfolios: numPortfolios,
          seed: parsedSeed !== null && !Number.isNaN(parsedSeed) ? parsedSeed : null,
          current_weights: evaluation?.weights ?? {},
        });
        setFrontier(payload);
        setRanWindow({ start: resolved.start, end: resolved.end });
        const bestIndex = payload.frontier.reduce(
          (best, point, index) => (point.sharpe > payload.frontier[best].sharpe ? index : best),
          0,
        );
        setFrontierIndex(goalId === "max_sharpe" ? bestIndex : 0);
      } catch (err: unknown) {
        setError(
          err instanceof Error
            ? err.message
            : "Something went wrong while finding your portfolio.",
        );
      } finally {
        setRunning(false);
      }
    },
    [
      selected,
      capital,
      universeOptions,
      resolved.start,
      resolved.end,
      windowError,
      setSelection,
      clearResult,
      showAdvanced,
      maxWeightPercent,
      goalId,
      evaluation,
      numPortfolios,
      seed,
      maxStocks,
      maxSectorPct,
      v2View.sectorByTicker,
    ],
  );

  function handleUsePortfolio() {
    if (!frontier) return;
    const point = frontier.frontier[Math.min(frontierIndex, frontier.frontier.length - 1)];
    if (!point) return;
    publishResult(toOptimizeResult(frontier, point, goalId, capital));
    setNotice("Saved this mix. The Risk and Rebalance pages now use it");
  }

  return (
    <section className="space-y-6">
      <StepCard
        number={1}
        title="Stocks to consider"
        description="Filter by sector, index and liquidity; the server returns the tickers that pass. Add all passing or pick tickers manually."
      >
        <UniverseFilterPanel
          selected={selected}
          maxStocks={maxStocks}
          onAddMany={addMany}
          onUniverse={setV2View}
        />
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void startFromVn30()} disabled={presetLoading}>
            {presetLoading ? "Loading\u2026" : "Start from VN30"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={clearAllSelected}
            disabled={selected.length === 0}
          >
            Clear all
          </Button>
        </div>

        <form onSubmit={handleSearchSubmit} className="mt-4 space-y-2">
          <label htmlFor="ticker-search" className="block text-sm font-medium text-fg">
            Ticker search
          </label>
          <div className="relative max-w-xs">
            <input
              id="ticker-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search ticker or company"
              className={`${inputClass} w-full`}
            />
            {suggestions.length !== 0 && (
              <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-strong bg-surface text-sm shadow-lg transition-opacity duration-150 ease-unslop">
                {suggestions.map((symbol) => (
                  <li key={symbol.code}>
                    <button
                      type="button"
                      onClick={() => addSymbol(symbol.code)}
                      className="flex min-h-[40px] w-full items-center justify-between px-3 py-2 text-left transition-colors duration-150 ease-unslop hover:bg-raised"
                    >
                      <span className="font-mono font-medium text-fg">{symbol.code}</span>
                      <span className="ml-2 truncate text-xs text-fg-muted">
                        {symbol.exchange}
                        {symbol.name ? ` \u00b7 ${symbol.name}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {selected.length !== 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {selected.map((code) => (
                <span
                  key={code}
                  className="inline-flex items-center gap-1 rounded-md border border-accent/25 bg-accent-subtle px-2 py-1 font-mono text-xs text-accent-ink"
                >
                  <span>{code}</span>
                  <button
                    type="button"
                    onClick={() => removeSymbol(code)}
                    aria-label={`Remove ${code}`}
                    className="inline-flex items-center justify-center rounded-sm text-accent-ink/80 transition-colors duration-150 ease-unslop hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <XIcon size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </form>

        {keptCount !== 0 && (
          <p className="mt-4 font-mono text-xs tabular-nums text-fg-secondary">
            {keptCount} kept &middot; {universeResult?.dropped.length ?? 0} dropped (
            {universeResult?.start ?? resolved.start} to {universeResult?.end ?? resolved.end})
          </p>
        )}

        {sizeWarnings.map((warning) => (
          <p
            key={warning}
            className="mt-3 rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn"
          >
            {warning}
          </p>
        ))}

        {universeResult && universeResult.dropped.length !== 0 && (
          <DroppedTable dropped={universeResult.dropped} />
        )}
      </StepCard>

      <StepCard number={2} title="Money" description="Where does the money come from?">
        <OptimizeCapital
          mode={capitalMode}
          newCapital={newCapital}
          onModeChange={setCapitalMode}
          onNewCapitalChange={setNewCapital}
        />
      </StepCard>

      <StepCard number={3} title="Goal" description="What do you want, in plain language?">
        <div className="grid gap-3 sm:grid-cols-3">
          {GOALS.map((goal) => (
            <label
              key={goal.id}
              className={`flex cursor-pointer items-start gap-2.5 rounded-lg border p-3.5 text-sm transition-colors duration-150 ease-unslop ${
                goalId === goal.id
                  ? "border-accent bg-accent-subtle/50"
                  : "border-hairline bg-surface hover:border-strong"
              }`}
            >
              <input
                type="radio"
                name="goal"
                checked={goalId === goal.id}
                onChange={() => setGoalId(goal.id)}
                className="mt-1 h-4 w-4 accent-accent"
              />
              <span>
                <span className="font-medium text-fg">{goal.label}</span>
                <InfoTip text={goal.detail} />
              </span>
            </label>
          ))}
        </div>
      </StepCard>

      <Card>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1.5 text-sm font-medium text-accent-ink transition-colors duration-150 ease-unslop hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm"
        >
          <span>{showAdvanced ? "Hide advanced settings" : "Advanced settings"}</span>
          {showAdvanced ? <ChevronUpIcon size={15} /> : <ChevronDownIcon size={15} />}
        </button>
        {showAdvanced && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5 text-sm">
              <span className="block font-medium text-fg">Max weight per stock (%)</span>
              <input
                type="number"
                min={0}
                max={100}
                value={maxWeightPercent}
                onChange={(event) => setMaxWeightPercent(event.target.value)}
                placeholder={`Default ${(defaultMaxWeight(keptCount || 1) * 100).toFixed(0)}%`}
                className={`${inputClass} w-full font-mono tabular-nums`}
              />
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="block font-medium text-fg">Max weight per sector (%)</span>
              <input
                type="number"
                min={0}
                max={100}
                value={maxSectorPct}
                onChange={(event) => setMaxSectorPct(event.target.value)}
                placeholder="Optional, e.g. 30"
                className={`${inputClass} w-full font-mono tabular-nums`}
              />
              <span className="block text-xs text-fg-muted">
                Applies to the frontier and the random cloud. Tickers without a sector count
                as &quot;Unknown&quot;.
              </span>
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="block font-medium text-fg">Benchmark</span>
              <select
                value={benchmark}
                onChange={(event) => setBenchmark(event.target.value)}
                className={`${selectClass} w-full`}
              >
                {(riskOptions?.benchmarks ?? []).map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="block font-medium text-fg">VaR confidence (%)</span>
              <input
                type="number"
                min={1}
                max={99}
                value={varConfidence}
                onChange={(event) => setVarConfidence(Number(event.target.value))}
                className={`${inputClass} w-full font-mono tabular-nums`}
              />
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="block font-medium text-fg">Number of random portfolios</span>
              <input
                type="number"
                min={1}
                max={maxPortfolios ?? undefined}
                value={numPortfolios}
                onChange={(event) => setNumPortfolios(Number(event.target.value))}
                className={`${inputClass} w-full font-mono tabular-nums`}
              />
              <span className="block text-xs text-fg-muted">
                {maxPortfolios ? `Up to ${maxPortfolios.toLocaleString("en-US")}. ` : ""}
                The statistics use every portfolio; the chart plots a sampled subset of them.
              </span>
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="block font-medium text-fg">Seed</span>
              <input
                type="text"
                value={seed}
                onChange={(event) => setSeed(event.target.value)}
                placeholder="Random seed (optional)"
                className={`${inputClass} w-full font-mono`}
              />
            </label>
          </div>
        )}
      </Card>

      <Card>
        <TimeframePicker
          selection={timeframe}
          latestDate={latestDate}
          onChange={(next) => setTimeframe("optimize", next)}
          copyLabel="Risk"
          onCopyOther={() => setTimeframe("optimize", timeframes.risk)}
        />
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => void handleFind()}
          disabled={running || selected.length === 0}
        >
          {running ? "Finding\u2026" : "Find my portfolio"}
        </Button>
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          {selected.length} tickers to consider
        </span>
      </div>

      <p className="rounded-lg border border-hairline bg-raised/50 px-3 py-2.5 text-xs text-fg-secondary">
        Price source: the optimizer, P&amp;L and risk pages read the V2 precomputed dataset
        (adjusted closes for returns, raw closes for share sizing). A ticker whose V2 history is
        missing or stale is reported explicitly instead of being valued from an older V1 series.
      </p>

      {error && <p className="text-sm text-negative">{error}</p>}
      {notice && <p className="text-sm text-positive">{notice}</p>}
      {outdated && !running && (
        <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          The timeframe changed. These results are from an earlier window; press Find my portfolio
          to update them.
        </p>
      )}

      {frontier && (
        <FrontierResults
          frontier={frontier}
          goalId={goalId}
          selectedIndex={frontierIndex}
          onSelect={setFrontierIndex}
          onUse={handleUsePortfolio}
          onOpenDetail={setDetailSymbol}
          dropped={universeResult?.dropped ?? []}
          sectorByTicker={v2View.sectorByTicker}
        />
      )}

      <TickerDetailDrawer
        symbol={detailSymbol}
        onClose={() => setDetailSymbol(null)}
        preset={v2Filter.preset}
      />
    </section>
  );
}

function StepCard({
  number,
  title,
  description,
  children,
}: {
  number: number;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <div className="flex items-baseline gap-2.5">
        <span className="font-mono text-xs font-medium text-accent-ink">Step {number}</span>
        <h2 className="text-base font-medium text-fg">{title}</h2>
      </div>
      {description && <p className="mt-1 text-sm text-fg-secondary">{description}</p>}
      <div className="mt-4">{children}</div>
    </Card>
  );
}

function MetricCard({ label, value, tip }: { label: string; value: string; tip: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-raised/50 p-3.5">
      <div className="flex items-center text-xs text-fg-muted">
        <span>{label}</span>
        <InfoTip text={tip} />
      </div>
      <div className="mt-1.5 font-mono text-xl font-medium tabular-nums text-fg">{value}</div>
    </div>
  );
}

function toOptimizeResult(
  frontier: FrontierResult,
  point: FrontierPoint,
  goalId: string,
  capital: number,
): OptimizeResult {
  const assumptions = frontier.assumptions;
  return {
    symbols: frontier.symbols,
    weights: point.weights,
    lots: point.lots,
    shares: point.shares,
    values: point.values,
    residual_cash: point.residual_cash,
    cash_reserve: 0,
    cash_reserve_value: 0,
    total_cash: point.residual_cash,
    expected_return: point.expected_return,
    volatility: point.volatility,
    sharpe: point.sharpe,
    solver_status: "frontier",
    solver_message: "chosen from the efficient frontier",
    binding_constraints: [],
    assumptions: {
      objective: goalId,
      return_estimator: { id: assumptions.return_estimator, params: {} },
      covariance_estimator: { id: assumptions.covariance_estimator, params: {} },
      constraints: [{ id: "max_weight", params: { max_weight: assumptions.max_weight } }],
      capital,
      investable_capital: capital,
      cash_reserve: 0,
      risk_free_rate: assumptions.risk_free_rate,
      risk_free_rate_provider: "user_settings",
      start: assumptions.start,
      end: assumptions.end,
      data_sources: assumptions.data_sources,
      prices_adjusted: assumptions.prices_adjusted,
      lot_sizes: assumptions.lot_sizes,
    },
    warnings: [],
  };
}

function FrontierResults({
  frontier,
  goalId,
  selectedIndex,
  onSelect,
  onUse,
  onOpenDetail,
  dropped,
  sectorByTicker,
}: {
  frontier: FrontierResult;
  goalId: string;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onUse: () => void;
  onOpenDetail: (code: string) => void;
  dropped: UniverseBuildResponse["dropped"];
  sectorByTicker: Record<string, string>;
}) {
  const points = frontier.frontier;
  const index = Math.min(selectedIndex, points.length - 1);
  const point = points[index];
  const bestIndex = points.reduce(
    (best, candidate, position) => (candidate.sharpe > points[best].sharpe ? position : best),
    0,
  );
  if (!point) return null;
  const remainingWarnings = (frontier.warnings ?? []).filter(
    (warning) => !warning.toLowerCase().startsWith("in-sample"),
  );
  return (
    <Card className="space-y-5">
      <FrontierChart result={frontier} selectedIndex={index} onSelect={onSelect} />

      <div className="space-y-2.5 rounded-lg border border-hairline bg-raised/40 p-3.5">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-fg">
            Risk level
            <InfoTip text="Slide from the steadiest mix (left) to the highest expected return (right)." />
          </span>
          <span className="font-mono text-xs tabular-nums text-fg-secondary">
            {(point.volatility * 100).toFixed(1)}% yearly swings
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={points.length - 1}
          value={index}
          onChange={(event) => onSelect(Number(event.target.value))}
          className="w-full accent-accent"
          aria-label="Risk level"
        />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onSelect(0)}>
            Lowest risk
          </Button>
          <Button size="sm" onClick={() => onSelect(bestIndex)}>
            Best return for the risk
          </Button>
        </div>
      </div>

      <p className="text-sm leading-6 text-fg-secondary">
        {frontierSentence(frontier, point, goalId)}
      </p>

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label="Expected return"
          value={`${(point.expected_return * 100).toFixed(2)}%`}
          tip="The average yearly return the historical estimates imply for this mix."
        />
        <MetricCard
          label="Volatility"
          value={`${(point.volatility * 100).toFixed(2)}%`}
          tip="How much the mix's yearly return has swung up and down. Lower means steadier."
        />
        <MetricCard
          label="Sharpe"
          value={point.sharpe.toFixed(3)}
          tip="Return above the risk-free rate for each unit of risk. Higher is better."
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={onUse}>
          Use this portfolio
        </Button>
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          Mix {index + 1} of {points.length} on the line
        </span>
      </div>

      <SectorAllocation weights={point.weights} sectorByTicker={sectorByTicker} />

      <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
        <table className="min-w-full text-sm">
          <thead>
            <tr className={tableHeaderRowClass}>
              <th className={`${tableHeaderCellClass} sticky left-0 z-10 bg-raised`}>
                Ticker
              </th>
              <th className={tableHeaderCellClass}>Sector</th>
              <th className={`${tableHeaderCellClass} text-right`}>Weight</th>
              <th className={`${tableHeaderCellClass} text-right`}>Lots</th>
              <th className={`${tableHeaderCellClass} text-right`}>Shares</th>
              <th className={`${tableHeaderCellClass} text-right`}>Value</th>
            </tr>
          </thead>
          <tbody>
            {frontier.symbols.map((code) => (
              <tr key={code} className={tableRowHoverClass}>
                <td
                  className={`${tableBodyCellClass} sticky left-0 z-10 bg-surface font-mono font-medium text-fg`}
                >
                  <span>{code}</span>
                  <button
                    type="button"
                    onClick={() => onOpenDetail(code)}
                    aria-label={`Show fundamentals for ${code}`}
                    className="ml-2 font-sans text-xs font-normal text-accent-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm"
                  >
                    Details
                  </button>
                </td>
                <td className={`${tableBodyCellClass} text-fg-secondary`}>
                  {sectorByTicker[code] ?? "Unknown"}
                </td>
                <td
                  className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                >
                  {formatWeight(point.weights[code] ?? 0)}
                </td>
                <td
                  className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                >
                  {point.lots[code] ?? 0}
                </td>
                <td
                  className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                >
                  {(point.shares[code] ?? 0).toLocaleString("en-US")}
                </td>
                <td
                  className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                >
                  {formatVnd(point.values[code] ?? 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-sm text-fg-secondary">
        <span className="font-medium text-fg">Residual cash:</span>{" "}
        <span className="font-mono tabular-nums">{formatVnd(point.residual_cash)}</span>
      </div>

      {remainingWarnings.map((warning) => (
        <p
          key={warning}
          className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn"
        >
          {warning}
        </p>
      ))}

      {dropped.length !== 0 && <DroppedTable dropped={dropped} />}

      <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
        In-sample warning: these weights come from historical estimates over the selected window.
        They are decision support, not a forecast or financial advice.
      </p>
    </Card>
  );
}

function SectorAllocation({
  weights,
  sectorByTicker,
}: {
  weights: Record<string, number>;
  sectorByTicker: Record<string, string>;
}) {
  const totals = useMemo(
    function () {
      const sums: Record<string, number> = {};
      for (const [code, weight] of Object.entries(weights)) {
        const sector = sectorByTicker[code] ?? "Unknown";
        sums[sector] = (sums[sector] ?? 0) + weight;
      }
      return Object.entries(sums).sort((a, b) => b[1] - a[1]);
    },
    [weights, sectorByTicker],
  );
  if (totals.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-fg">Sector allocation</h3>
      <p className="text-xs text-fg-muted">
        How the optimized mix splits across sectors (market cap is full, not free-float).
      </p>
      <div className="space-y-1.5">
        {totals.map(([sector, weight]) => (
          <div key={sector} className="flex items-center gap-3 text-xs">
            <span className="w-36 truncate text-fg-secondary">{sector}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-sm bg-raised">
              <div
                className="h-2 rounded-sm bg-accent"
                style={{ width: `${Math.min(100, weight * 100).toFixed(1)}%` }}
              />
            </div>
            <span className="w-14 text-right font-mono tabular-nums text-fg">
              {formatWeight(weight)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DroppedTable({ dropped }: { dropped: UniverseBuildResponse["dropped"] }) {
  return (
    <div className="mt-4 space-y-2">
      <h3 className="text-sm font-medium text-fg">Dropped tickers</h3>
      <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
        <table className="min-w-full text-sm">
          <thead>
            <tr className={tableHeaderRowClass}>
              <th className={tableHeaderCellClass}>Ticker</th>
              <th className={tableHeaderCellClass}>Reason</th>
            </tr>
          </thead>
          <tbody>
            {dropped.map((item) => (
              <tr key={item.code} className={tableRowHoverClass}>
                <td className={`${tableBodyCellClass} font-mono font-medium text-fg`}>
                  {item.code}
                </td>
                <td className={`${tableBodyCellClass} text-fg-secondary`}>{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
