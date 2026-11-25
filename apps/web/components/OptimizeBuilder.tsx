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

/** The fixed sensible filters: everything except the single-exchange filter. */
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
  const { selection, setSelection } = useUniverse();
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
  // Seed an empty stock list with the portfolio's tickers once.
  useEffect(function () {
    if (portfolioSeeded.current || portfolioSymbols.length === 0) return;
    portfolioSeeded.current = true;
    setSelected((current) => (current.length ? current : [...portfolioSymbols]));
  }, [portfolioSymbols]);

  // Load the option catalogues, the symbol list for search and the latest data date.
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
        // The cloud cap is published by the API so the input never hardcodes it.
        if (optimizePayload.frontier_defaults.max_portfolios) {
          setMaxPortfolios(optimizePayload.frontier_defaults.max_portfolios);
        }
      })
      .catch(function () {
        // The search and fixed filters degrade gracefully if the API is down.
      });
    return function () {
      active = false;
    };
  }, []);

  const suggestions = useMemo(function () {
    const query = search.trim().toUpperCase();
    if (!query) return [];
    return universeSymbols
      .filter(
        (symbol) =>
          symbol.code.includes(query) || (symbol.name ?? "").toUpperCase().includes(query),
      )
      .filter((symbol) => !selected.includes(symbol.code))
      .slice(0, 8);
  }, [search, universeSymbols, selected]);

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
      setNotice(`Loaded ${response.count} VN30 stocks.`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load VN30.");
    } finally {
      setPresetLoading(false);
    }
  }

  const capital = resolveCapital(capitalMode, evaluation?.total_value ?? null, newCapital);
  const keptCount = universeResult?.symbols.length ?? 0;
  const sizeWarnings = keptCount ? universeSizeWarnings(keptCount) : [];

  const handleFind = useCallback(async function () {
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
          `Raised the max weight to ${(cap.value * 100).toFixed(0)}% so the portfolio can be fully invested.`,
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
      setError(err instanceof Error ? err.message : "Something went wrong while finding your portfolio.");
    } finally {
      setRunning(false);
    }
  }, [
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
  ]);

  function handleUsePortfolio() {
    if (!frontier) return;
    const point = frontier.frontier[Math.min(frontierIndex, frontier.frontier.length - 1)];
    if (!point) return;
    publishResult(toOptimizeResult(frontier, point, goalId, capital));
    setNotice("Saved this mix. The Risk and Rebalance pages now use it.");
  }

  return (
    <section className="space-y-6">
      <StepCard number={1} title="Stocks to consider" description="Filter by sector, index and liquidity; the server returns the tickers that pass (the same filter_universe the Sector tab uses). Add all passing or pick tickers manually.">
        <UniverseFilterPanel
          selected={selected}
          maxStocks={maxStocks}
          onAddMany={addMany}
          onUniverse={setV2View}
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => startFromVn30()} disabled={presetLoading} className="rounded-md border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-900">
            {presetLoading ? "Loading\u2026" : "Start from VN30"}
          </button>
        </div>

        <form onSubmit={handleSearchSubmit} className="mt-3 space-y-2">
          <label htmlFor="ticker-search" className="block text-sm font-medium">Ticker search</label>
          <div className="relative">
            <input id="ticker-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Type a code or name (e.g. VNM)" className="w-72 rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900" />
            {suggestions.length !== 0 && (
              <ul className="absolute z-10 mt-1 max-h-56 w-72 overflow-auto rounded-md border border-gray-200 bg-white text-sm shadow dark:border-gray-700 dark:bg-gray-900">
                {suggestions.map((symbol) => (
                  <li key={symbol.code}>
                    <button type="button" onClick={() => addSymbol(symbol.code)} className="flex w-full items-center justify-between px-3 py-1 text-left hover:bg-gray-100 dark:hover:bg-gray-800">
                      <span className="font-medium">{symbol.code}</span>
                      <span className="ml-2 truncate text-xs text-gray-500 dark:text-gray-400">{symbol.exchange}{symbol.name ? ` \u00b7 ${symbol.name}` : ""}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {selected.length !== 0 && (
            <div className="flex flex-wrap gap-2 pt-1">
              {selected.map((code) => (
                <span key={code} className="flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-800 dark:bg-blue-950 dark:text-blue-200">{code}<button type="button" onClick={() => removeSymbol(code)} aria-label={`Remove ${code}`} className="text-blue-600 hover:text-blue-900 dark:text-blue-300">&times;</button></span>
              ))}
            </div>
          )}
        </form>

        {keptCount !== 0 && (
          <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">{keptCount} kept &middot; {universeResult?.dropped.length ?? 0} dropped ({universeResult?.start ?? resolved.start} to {universeResult?.end ?? resolved.end})</p>
        )}

        {sizeWarnings.map((warning) => (
          <p key={warning} className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">{warning}</p>
        ))}

        {universeResult && universeResult.dropped.length !== 0 && <DroppedTable dropped={universeResult.dropped} />}
      </StepCard>

      <StepCard number={2} title="Money" description="Where does the money come from?">
        <OptimizeCapital mode={capitalMode} newCapital={newCapital} onModeChange={setCapitalMode} onNewCapitalChange={setNewCapital} />
      </StepCard>

      <StepCard number={3} title="Goal" description="What do you want, in plain language?">
        <div className="grid gap-2 sm:grid-cols-3">
          {GOALS.map((goal) => (
            <label key={goal.id} className="flex items-start gap-2 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-800">
              <input type="radio" name="goal" checked={goalId === goal.id} onChange={() => setGoalId(goal.id)} className="mt-1" />
              <span>
                <span className="font-medium">{goal.label}</span>
                <Tip text={goal.detail} />
              </span>
            </label>
          ))}
        </div>
      </StepCard>

      <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
        <button type="button" onClick={() => setShowAdvanced(!showAdvanced)} className="text-sm font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400">{showAdvanced ? "Hide advanced settings" : "Advanced settings"}</button>
        {showAdvanced && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="block font-medium">Max weight per stock (%)</span>
              <input type="number" min={0} max={100} value={maxWeightPercent} onChange={(event) => setMaxWeightPercent(event.target.value)} placeholder={`Default ${(defaultMaxWeight(keptCount || 1) * 100).toFixed(0)}%`} className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900" />
            </label>
            <label className="block text-sm">
              <span className="block font-medium">Max weight per sector (%)</span>
              <input type="number" min={0} max={100} value={maxSectorPct} onChange={(event) => setMaxSectorPct(event.target.value)} placeholder="Optional, e.g. 30" className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900" />
              <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
                Applies to the frontier and the random cloud. Tickers without a sector count
                as &quot;Unknown&quot;.
              </span>
            </label>
            <label className="block text-sm">
              <span className="block font-medium">Benchmark</span>
              <select value={benchmark} onChange={(event) => setBenchmark(event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900">
                {(riskOptions?.benchmarks ?? []).map((item) => (
                  <option key={item.code} value={item.code}>{item.name}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="block font-medium">VaR confidence (%)</span>
              <input type="number" min={1} max={99} value={varConfidence} onChange={(event) => setVarConfidence(Number(event.target.value))} className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900" />
            </label>
            <label className="block text-sm">
              <span className="block font-medium">Number of random portfolios</span>
              <input type="number" min={1} max={maxPortfolios ?? undefined} value={numPortfolios} onChange={(event) => setNumPortfolios(Number(event.target.value))} className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900" />
              <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
                {maxPortfolios
                  ? `Up to ${maxPortfolios.toLocaleString()}. `
                  : ""}
                The statistics use every portfolio; the chart plots a sampled subset of
                them.
              </span>
            </label>
            <label className="block text-sm">
              <span className="block font-medium">Seed</span>
              <input type="text" value={seed} onChange={(event) => setSeed(event.target.value)} placeholder="leave blank for a random seed" className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900" />
            </label>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
        <TimeframePicker
          selection={timeframe}
          latestDate={latestDate}
          onChange={(next) => setTimeframe("optimize", next)}
          copyLabel="Risk"
          onCopyOther={() => setTimeframe("optimize", timeframes.risk)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={handleFind} disabled={running || selected.length === 0} className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400">{running ? "Finding\u2026" : "Find my portfolio"}</button>
        <span className="text-xs text-gray-500 dark:text-gray-400">{selected.length} tickers to consider</span>
      </div>

      <p className="rounded-md bg-gray-50 p-2 text-xs text-gray-600 dark:bg-gray-900 dark:text-gray-300">
        Price source: the optimizer, P&amp;L and risk pages read the V2 precomputed dataset
        (adjusted closes for returns, raw closes for share sizing). A ticker whose V2 history is
        missing or stale is reported explicitly instead of being valued from an older V1 series.
      </p>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {notice && <p className="text-sm text-green-600 dark:text-green-400">{notice}</p>}
      {outdated && !running && (
        <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          The timeframe changed. These results are from an earlier window; press Find my portfolio to
          update them.
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
function StepCard({ number, title, description, children }: { number: number; title: string; description?: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">Step {number}</span>
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      {description && <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{description}</p>}
      <div className="mt-3">{children}</div>
    </div>
  );
}

function Tip({ text }: { text: string }) {
  return (
    <span title={text} aria-label={text} className="ml-1 cursor-help rounded-full border border-gray-300 px-1 text-[10px] leading-4 text-gray-500 dark:border-gray-600 dark:text-gray-400">?</span>
  );
}

function MetricCard({ label, value, tip }: { label: string; value: string; tip: string }) {
  return (
    <div className="rounded-md bg-gray-50 p-3 dark:bg-gray-900">
      <div className="flex items-center text-xs text-gray-500 dark:text-gray-400">{label}<Tip text={tip} /></div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
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
    <div className="space-y-4 rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <FrontierChart result={frontier} selectedIndex={index} onSelect={onSelect} />

      <div className="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-800">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            Risk level
            <Tip text="Slide from the steadiest mix (left) to the highest expected return (right)." />
          </span>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {(point.volatility * 100).toFixed(1)}% yearly swings
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={points.length - 1}
          value={index}
          onChange={(event) => onSelect(Number(event.target.value))}
          className="w-full"
          aria-label="Risk level"
        />
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => onSelect(0)} className="rounded-md border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-900">
            Lowest risk
          </button>
          <button type="button" onClick={() => onSelect(bestIndex)} className="rounded-md border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-900">
            Best return for the risk
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-700 dark:text-gray-200">{frontierSentence(frontier, point, goalId)}</p>

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="Expected return" value={`${(point.expected_return * 100).toFixed(2)}%`} tip="The average yearly return the historical estimates imply for this mix." />
        <MetricCard label="Volatility" value={`${(point.volatility * 100).toFixed(2)}%`} tip="How much the mix's yearly return has swung up and down. Lower means steadier." />
        <MetricCard label="Sharpe" value={point.sharpe.toFixed(3)} tip="Return above the risk-free rate for each unit of risk. Higher is better." />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={onUse} className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700">
          Use this portfolio
        </button>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          Mix {index + 1} of {points.length} on the line
        </span>
      </div>

      <SectorAllocation weights={point.weights} sectorByTicker={sectorByTicker} />

      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
          <thead className="bg-gray-50 text-left dark:bg-gray-900">
            <tr>
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Sector</th>
              <th className="px-3 py-2 font-medium">Weight</th>
              <th className="px-3 py-2 font-medium">Lots</th>
              <th className="px-3 py-2 font-medium">Shares</th>
              <th className="px-3 py-2 font-medium">Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {frontier.symbols.map((code) => (
              <tr key={code}>
                <td className="px-3 py-2 font-medium">
                  <span>{code}</span>
                  <button
                    type="button"
                    onClick={() => onOpenDetail(code)}
                    aria-label={`Show fundamentals for ${code}`}
                    className="ml-2 text-xs font-normal text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                  >
                    Details
                  </button>
                </td>
                <td className="px-3 py-2 text-gray-600 dark:text-gray-300">{sectorByTicker[code] ?? "Unknown"}</td>
                <td className="px-3 py-2">{formatWeight(point.weights[code] ?? 0)}</td>
                <td className="px-3 py-2">{point.lots[code] ?? 0}</td>
                <td className="px-3 py-2">{point.shares[code] ?? 0}</td>
                <td className="px-3 py-2">{formatVnd(point.values[code] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-sm">
        <span className="font-medium">Residual cash:</span> {formatVnd(point.residual_cash)}
      </div>

      {remainingWarnings.map((warning) => (
        <p key={warning} className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          {warning}
        </p>
      ))}

      {dropped.length !== 0 && <DroppedTable dropped={dropped} />}

      <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
        In-sample warning: these weights come from historical estimates over the selected window.
        They are decision support, not a forecast or financial advice.
      </p>
    </div>
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
    <div className="space-y-1">
      <h3 className="text-sm font-semibold">Sector allocation</h3>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        How the optimized mix splits across sectors (market cap is full, not free-float).
      </p>
      {totals.map(([sector, weight]) => (
        <div key={sector} className="flex items-center gap-2 text-xs">
          <span className="w-32 truncate">{sector}</span>
          <div className="h-2 flex-1 rounded bg-gray-100 dark:bg-gray-800">
            <div
              className="h-2 rounded bg-blue-500"
              style={{ width: `${Math.min(100, weight * 100).toFixed(1)}%` }}
            />
          </div>
          <span className="w-12 text-right">{formatWeight(weight)}</span>
        </div>
      ))}
    </div>
  );
}

function DroppedTable({ dropped }: { dropped: UniverseBuildResponse["dropped"] }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">Dropped tickers</h3>
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
          <thead className="bg-gray-50 text-left dark:bg-gray-900">
            <tr>
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {dropped.map((item) => (
              <tr key={item.code}>
                <td className="px-3 py-2 font-medium">{item.code}</td>
                <td className="px-3 py-2 text-gray-600 dark:text-gray-300">{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}