"use client";

/**
 * Rebalance page: turn current holdings plus target weights into a placeable
 * order list.
 *
 * Holdings and cash are pre-filled from the shared portfolio store and stay
 * editable here. Target weights start from the optimized mix saved on the
 * Optimize page (the store's chosen portfolio) or, when there is none, from the
 * current weights; they stay editable. Holdings and target weights can also be
 * imported from CSV, and the resulting order list is exportable to CSV. Cost
 * models and policies (with their parameters) are rendered from
 * `GET /api/v1/rebalance/options`, so a new core policy appears here without a
 * UI change.
 *
 * Prices are the latest close; sells are planned before buys, orders round down
 * to whole lots and T+2 settlement is not modeled in V1.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import {
  fetchRebalanceOptions,
  fetchSymbols,
  runRebalance,
  type ParameterSchemaProperty,
  type RebalanceOption,
  type RebalanceOptions,
  type RebalanceResult,
  type SymbolInfo,
} from "@/lib/api";
import { formatVnd } from "@/lib/format";
import { useOptimize } from "@/lib/optimize-context";
import { parseHoldingsCsv } from "@/lib/portfolio-csv";
import { usePortfolio } from "@/lib/portfolio-context";
import type { PortfolioHolding } from "@/lib/portfolio";
import {
  ordersToCsv,
  parseTargetWeightsCsv,
  type TargetWeightRow,
} from "@/lib/rebalance-csv";
import { targetRowsFromHoldings, targetRowsFromWeights } from "@/lib/rebalance-targets";
import { useUserSettings } from "@/lib/user-settings-context";

import { CurrentVsTargetChart } from "./charts/CurrentVsTargetChart";

function parseWhole(value: string): number {
  const parsed = Math.trunc(Number(value));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function downloadTextFile(filename: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function readTextFile(
  event: ChangeEvent<HTMLInputElement>,
  onText: (text: string) => void,
): Promise<void> {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) {
    return;
  }
  onText(await file.text());
}

function propertyType(property: ParameterSchemaProperty): string {
  if (property.type) return property.type;
  for (const variant of property.anyOf ?? []) {
    if (variant.type && variant.type !== "null") return variant.type;
  }
  return "string";
}

function defaultParams(option: RebalanceOption | undefined): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [name, property] of Object.entries(option?.parameter_schema?.properties ?? {})) {
    if (property.default !== undefined) {
      params[name] = property.default;
      continue;
    }
    const type = propertyType(property);
    params[name] = type === "boolean" ? false : type === "integer" || type === "number" ? 0 : "";
  }
  return params;
}

export function RebalanceCalculator() {
  const { holdings: portfolioHoldings, cash: portfolioCash, evaluation } = usePortfolio();
  const { ready } = useUserSettings();
  const { chosenWeights } = useOptimize();

  const [holdings, setHoldings] = useState<PortfolioHolding[]>([]);
  const [cash, setCash] = useState(0);
  const [targets, setTargets] = useState<TargetWeightRow[]>([]);
  const [targetsFrom, setTargetsFrom] = useState<"optimized" | "current" | "manual">("current");
  const [options, setOptions] = useState<RebalanceOptions | null>(null);
  const [policy, setPolicy] = useState("full");
  const [policyParams, setPolicyParams] = useState<Record<string, unknown>>({});
  const [costModel, setCostModel] = useState("vn");
  const [minNotional, setMinNotional] = useState(1_000_000);
  const [universe, setUniverse] = useState<SymbolInfo[]>([]);
  const [result, setResult] = useState<RebalanceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const holdingsPrefilled = useRef(false);
  const targetsPrefilled = useRef(false);

  useEffect(() => {
    let active = true;
    fetchRebalanceOptions()
      .then((payload) => {
        if (!active) return;
        setOptions(payload);
        setCostModel(payload.defaults.cost_model);
        setPolicy(payload.defaults.policy);
        setMinNotional(payload.defaults.min_notional);
        setPolicyParams(
          defaultParams(payload.policies.find((item) => item.id === payload.defaults.policy)),
        );
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load rebalance options");
        }
      });
    fetchSymbols()
      .then((payload) => {
        if (active) setUniverse(payload.symbols);
      })
      .catch(() => {
        // Ticker suggestions are optional; the user can still type codes.
      });
    return () => {
      active = false;
    };
  }, []);

  // Pre-fill holdings and cash once from the shared portfolio.
  useEffect(() => {
    if (holdingsPrefilled.current) return;
    if (portfolioHoldings.length === 0 && portfolioCash === 0) return;
    setHoldings(portfolioHoldings.map((holding) => ({ ...holding })));
    setCash(portfolioCash);
    holdingsPrefilled.current = true;
  }, [portfolioHoldings, portfolioCash]);

  // Pre-fill target weights once: the optimized mix saved on the Optimize page
  // wins, otherwise the current portfolio weights are a sensible starting point.
  useEffect(() => {
    if (targetsPrefilled.current) return;
    if (chosenWeights !== null && Object.keys(chosenWeights).length > 0) {
      setTargets(targetRowsFromWeights(chosenWeights));
      setTargetsFrom("optimized");
      targetsPrefilled.current = true;
      return;
    }
    if (!evaluation || evaluation.total_value <= 0) return;
    setTargets(targetRowsFromHoldings(evaluation.holdings));
    setTargetsFrom("current");
    targetsPrefilled.current = true;
  }, [chosenWeights, evaluation]);

  const targetSum = useMemo(
    () => targets.reduce((sum, row) => sum + row.weight_percent, 0),
    [targets],
  );

  const updateHolding = useCallback(
    (symbol: string, changes: Partial<Omit<PortfolioHolding, "symbol">>) => {
      setHoldings((current) =>
        current.map((holding) =>
          holding.symbol === symbol ? { ...holding, ...changes } : holding,
        ),
      );
    },
    [],
  );

  const removeHolding = useCallback((symbol: string) => {
    setHoldings((current) => current.filter((holding) => holding.symbol !== symbol));
  }, []);

  const addHolding = useCallback((symbol: string) => {
    const code = symbol.trim().toUpperCase();
    if (!code) return;
    setHoldings((current) =>
      current.some((holding) => holding.symbol === code)
        ? current
        : [...current, { symbol: code, shares: 0, avg_cost: null }],
    );
  }, []);

  const updateTarget = useCallback((symbol: string, weightPercent: number) => {
    setTargets((current) =>
      current.map((row) =>
        row.symbol === symbol ? { ...row, weight_percent: weightPercent } : row,
      ),
    );
    setTargetsFrom("manual");
  }, []);

  const removeTarget = useCallback((symbol: string) => {
    setTargets((current) => current.filter((row) => row.symbol !== symbol));
    setTargetsFrom("manual");
  }, []);

  const addTarget = useCallback((symbol: string) => {
    const code = symbol.trim().toUpperCase();
    if (!code) return;
    setTargets((current) =>
      current.some((row) => row.symbol === code)
        ? current
        : [...current, { symbol: code, weight_percent: 0 }],
    );
    setTargetsFrom("manual");
  }, []);

  const matchCurrent = useCallback(() => {
    if (!evaluation || evaluation.total_value <= 0) {
      setNotice("No valuation yet; add holdings and cash first.");
      return;
    }
    setTargets(targetRowsFromHoldings(evaluation.holdings));
    setTargetsFrom("current");
    setNotice("Target weights set to your current weights.");
  }, [evaluation]);

  const useOptimizedWeights = useCallback(() => {
    if (chosenWeights === null || Object.keys(chosenWeights).length === 0) {
      setNotice("Run Optimize and press \u201cUse this portfolio\u201d first.");
      return;
    }
    setTargets(targetRowsFromWeights(chosenWeights));
    setTargetsFrom("optimized");
    setNotice("Target weights set to your optimized mix.");
  }, [chosenWeights]);

  const handlePolicyChange = useCallback(
    (id: string) => {
      setPolicy(id);
      setPolicyParams(defaultParams(options?.policies.find((item) => item.id === id)));
    },
    [options],
  );

  const importHoldingsCsv = useCallback((text: string) => {
    const parsed = parseHoldingsCsv(text);
    if (parsed.errors.length > 0) {
      setError(`Holdings CSV: ${parsed.errors.slice(0, 3).join("; ")}`);
      return;
    }
    setHoldings(parsed.holdings);
    setError(null);
    setNotice(`Imported ${parsed.holdings.length} holdings.`);
  }, []);

  const importTargetsCsv = useCallback((text: string) => {
    const parsed = parseTargetWeightsCsv(text);
    if (parsed.errors.length > 0) {
      setError(`Target CSV: ${parsed.errors.slice(0, 3).join("; ")}`);
      return;
    }
    setTargets(parsed.rows);
    setTargetsFrom("manual");
    setError(null);
    setNotice(`Imported ${parsed.rows.length} target weights.`);
  }, []);

  const handleRun = useCallback(async () => {
    if (!options) return;
    if (holdings.length === 0 && cash <= 0) {
      setError("Add at least one holding or some cash.");
      return;
    }
    if (targetSum > 100) {
      setError("Target weights must not exceed 100%.");
      return;
    }
    const targetWeights: Record<string, number> = {};
    for (const row of targets) {
      const code = row.symbol.trim().toUpperCase();
      if (!code || !(row.weight_percent > 0)) continue;
      targetWeights[code] = (targetWeights[code] ?? 0) + row.weight_percent / 100;
    }
    if (Object.keys(targetWeights).length === 0) {
      setError("Add at least one target weight above 0%.");
      return;
    }
    setRunning(true);
    setError(null);
    setNotice(null);
    setResult(null);
    try {
      const payload = await runRebalance({
        holdings: holdings.map((holding) => ({
          symbol: holding.symbol,
          shares: holding.shares,
          avg_cost: holding.avg_cost,
        })),
        cash,
        target_weights: targetWeights,
        cost_model: costModel,
        policy,
        policy_params: policyParams,
        min_notional: minNotional,
      });
      setResult(payload);
    } catch (err: unknown) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Rebalance failed");
    } finally {
      setRunning(false);
    }
  }, [cash, costModel, holdings, minNotional, options, policy, policyParams, targets, targetSum]);

  return (
    <section className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-300">
        Holdings are pre-filled from your{" "}
        <Link href="/portfolio" className="text-blue-600 hover:underline dark:text-blue-400">
          Portfolio
        </Link>{" "}
        and stay editable here. Target weights start from the mix you saved with{" "}
        <Link href="/optimize" className="text-blue-600 hover:underline dark:text-blue-400">
          Optimize
        </Link>{" "}
        and stay editable too; enter them as a percent of total value, and the remainder
        is cash.
      </p>

      <HoldingsEditor
        holdings={holdings}
        cash={cash}
        universe={universe}
        onCashChange={setCash}
        onAdd={addHolding}
        onUpdate={updateHolding}
        onRemove={removeHolding}
        onImportCsv={importHoldingsCsv}
      />

      <TargetEditor
        targets={targets}
        universe={universe}
        targetSum={targetSum}
        targetsFrom={targetsFrom}
        hasOptimizedWeights={chosenWeights !== null && Object.keys(chosenWeights).length > 0}
        onAdd={addTarget}
        onUpdate={updateTarget}
        onRemove={removeTarget}
        onMatchCurrent={matchCurrent}
        onUseOptimized={useOptimizedWeights}
        onImportCsv={importTargetsCsv}
      />

      {options ? (
        <PolicyControls
          options={options}
          policy={policy}
          policyParams={policyParams}
          costModel={costModel}
          minNotional={minNotional}
          onPolicyChange={handlePolicyChange}
          onParamChange={(name, value) =>
            setPolicyParams((current) => ({ ...current, [name]: value }))
          }
          onCostModelChange={setCostModel}
          onMinNotionalChange={setMinNotional}
        />
      ) : (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading options&hellip;</p>
      )}

      <div className="rounded-md bg-gray-50 p-3 text-xs text-gray-600 dark:bg-gray-900 dark:text-gray-300">
        Prices are the latest close. Sells are planned before buys, orders round down to
        whole lots, orders below the minimum notional are skipped, and T+2 settlement is
        not modeled in V1 &mdash; check the list against your broker before placing it.
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={handleRun}
          disabled={running || !options || !ready}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
        >
          {running ? "Planning\u2026" : "Plan rebalance"}
        </button>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {holdings.length} holdings &middot; {formatVnd(cash)} cash &middot; {targets.length}{" "}
          targets
        </span>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {notice && <p className="text-sm text-green-600 dark:text-green-400">{notice}</p>}
      {result && <RebalanceResults result={result} />}
    </section>
  );
}

function SymbolSearch({
  onPick,
  existing,
  universe,
  placeholder,
}: {
  onPick: (code: string) => void;
  existing: Set<string>;
  universe: SymbolInfo[];
  placeholder: string;
}) {
  const [query, setQuery] = useState("");
  const suggestions = useMemo(() => {
    const text = query.trim().toUpperCase();
    if (!text) return [];
    return universe
      .filter(
        (symbol) =>
          (symbol.code.includes(text) || (symbol.name ?? "").toUpperCase().includes(text)) &&
          !existing.has(symbol.code),
      )
      .slice(0, 8);
  }, [existing, query, universe]);

  function pick(code: string) {
    onPick(code);
    setQuery("");
  }

  return (
    <div className="relative">
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            const code = query.trim().toUpperCase();
            if (code) pick(code);
          }
        }}
        placeholder={placeholder}
        className="w-56 rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-700 dark:bg-gray-900"
      />
      {suggestions.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-56 w-56 overflow-auto rounded-md border border-gray-200 bg-white text-sm shadow dark:border-gray-700 dark:bg-gray-900">
          {suggestions.map((symbol) => (
            <li key={symbol.code}>
              <button
                type="button"
                onClick={() => pick(symbol.code)}
                className="flex w-full items-center justify-between px-3 py-1 text-left hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <span className="font-medium">{symbol.code}</span>
                <span className="ml-2 truncate text-xs text-gray-500 dark:text-gray-400">
                  {symbol.exchange}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadLabel({
  label,
  onText,
}: {
  label: string;
  onText: (text: string) => void;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center rounded-md border border-gray-300 px-2 py-1.5 text-xs text-gray-600 hover:border-blue-400 dark:border-gray-700 dark:text-gray-300 dark:hover:border-blue-400">
      {label}
      <input
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(event) => void readTextFile(event, onText)}
      />
    </label>
  );
}

function HoldingsEditor({
  holdings,
  cash,
  universe,
  onCashChange,
  onAdd,
  onUpdate,
  onRemove,
  onImportCsv,
}: {
  holdings: PortfolioHolding[];
  cash: number;
  universe: SymbolInfo[];
  onCashChange: (cash: number) => void;
  onAdd: (symbol: string) => void;
  onUpdate: (symbol: string, changes: Partial<Omit<PortfolioHolding, "symbol">>) => void;
  onRemove: (symbol: string) => void;
  onImportCsv: (text: string) => void;
}) {
  const existing = useMemo(() => new Set(holdings.map((holding) => holding.symbol)), [holdings]);
  return (
    <div className="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Current holdings</h2>
        <div className="flex flex-wrap items-center gap-2">
          <SymbolSearch
            onPick={onAdd}
            existing={existing}
            universe={universe}
            placeholder="Add holding"
          />
          <UploadLabel label="Upload holdings CSV" onText={onImportCsv} />
        </div>
      </div>
      <label className="block text-xs">
        <span className="text-gray-600 dark:text-gray-300">Cash (VND)</span>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          step={1000}
          value={cash === 0 ? "" : String(cash)}
          placeholder="0"
          onChange={(event) => onCashChange(parseWhole(event.target.value))}
          className="mt-1 w-48 rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
        />
      </label>
      {holdings.length === 0 ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          No holdings yet; add a ticker above.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
            <thead className="bg-gray-50 text-left text-xs dark:bg-gray-900">
              <tr>
                <th className="px-2 py-1 font-medium">Ticker</th>
                <th className="px-2 py-1 font-medium">Shares</th>
                <th className="px-2 py-1 font-medium">Avg cost (VND)</th>
                <th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {holdings.map((holding) => (
                <tr key={holding.symbol}>
                  <td className="px-2 py-1 font-medium">{holding.symbol}</td>
                  <td className="px-2 py-1">
                    <input
                      type="number"
                      inputMode="numeric"
                      min={0}
                      step={100}
                      value={holding.shares === 0 ? "" : String(holding.shares)}
                      placeholder="0"
                      onChange={(event) =>
                        onUpdate(holding.symbol, { shares: parseWhole(event.target.value) })
                      }
                      className="w-24 rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      type="number"
                      inputMode="numeric"
                      min={0}
                      step={100}
                      value={holding.avg_cost ?? ""}
                      placeholder="optional"
                      onChange={(event) =>
                        onUpdate(holding.symbol, {
                          avg_cost:
                            event.target.value === "" ? null : parseWhole(event.target.value),
                        })
                      }
                      className="w-28 rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
                    />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      onClick={() => onRemove(holding.symbol)}
                      aria-label={`Remove ${holding.symbol}`}
                      className="text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
                    >
                      &times;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TargetEditor({
  targets,
  universe,
  targetSum,
  targetsFrom,
  hasOptimizedWeights,
  onAdd,
  onUpdate,
  onRemove,
  onMatchCurrent,
  onUseOptimized,
  onImportCsv,
}: {
  targets: TargetWeightRow[];
  universe: SymbolInfo[];
  targetSum: number;
  targetsFrom: "optimized" | "current" | "manual";
  hasOptimizedWeights: boolean;
  onAdd: (symbol: string) => void;
  onUpdate: (symbol: string, weightPercent: number) => void;
  onRemove: (symbol: string) => void;
  onMatchCurrent: () => void;
  onUseOptimized: () => void;
  onImportCsv: (text: string) => void;
}) {
  const existing = useMemo(() => new Set(targets.map((row) => row.symbol)), [targets]);
  return (
    <div className="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Target weights</h2>
        <div className="flex flex-wrap items-center gap-2">
          <SymbolSearch
            onPick={onAdd}
            existing={existing}
            universe={universe}
            placeholder="Add target"
          />
          <button
            type="button"
            onClick={onUseOptimized}
            disabled={!hasOptimizedWeights}
            title={
              hasOptimizedWeights
                ? undefined
                : "Run Optimize and press \u201cUse this portfolio\u201d first."
            }
            className="rounded-md border border-gray-300 px-2 py-1.5 text-xs text-gray-600 hover:border-blue-400 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:border-blue-400"
          >
            Use optimized weights
          </button>
          <button
            type="button"
            onClick={onMatchCurrent}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-xs text-gray-600 hover:border-blue-400 dark:border-gray-700 dark:text-gray-300 dark:hover:border-blue-400"
          >
            Use current weights
          </button>
          <UploadLabel label="Upload target CSV" onText={onImportCsv} />
        </div>
      </div>
      {targetsFrom === "optimized" && (
        <p className="text-xs text-green-700 dark:text-green-400">
          Started from the optimized mix saved on the Optimize page; edit any value.
        </p>
      )}
      {targetsFrom === "current" && targets.length > 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Started from your current portfolio weights; edit any value or use the
          optimized mix.
        </p>
      )}
      {targets.length === 0 ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          No targets yet; add a ticker, use your current weights or the optimized
          mix.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
            <thead className="bg-gray-50 text-left text-xs dark:bg-gray-900">
              <tr>
                <th className="px-2 py-1 font-medium">Ticker</th>
                <th className="px-2 py-1 font-medium">Target weight (%)</th>
                <th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {targets.map((row) => (
                <tr key={row.symbol}>
                  <td className="px-2 py-1 font-medium">{row.symbol}</td>
                  <td className="px-2 py-1">
                    <input
                      type="number"
                      inputMode="decimal"
                      min={0}
                      max={100}
                      step={0.5}
                      value={row.weight_percent === 0 ? "" : String(row.weight_percent)}
                      placeholder="0"
                      onChange={(event) =>
                        onUpdate(row.symbol, Number(event.target.value))
                      }
                      className="w-24 rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
                    />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      onClick={() => onRemove(row.symbol)}
                      aria-label={`Remove ${row.symbol}`}
                      className="text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
                    >
                      &times;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Total {targetSum.toFixed(1)}% &middot; cash {Math.max(0, 100 - targetSum).toFixed(1)}%
      </p>
    </div>
  );
}

function PolicyControls({
  options,
  policy,
  policyParams,
  costModel,
  minNotional,
  onPolicyChange,
  onParamChange,
  onCostModelChange,
  onMinNotionalChange,
}: {
  options: RebalanceOptions;
  policy: string;
  policyParams: Record<string, unknown>;
  costModel: string;
  minNotional: number;
  onPolicyChange: (id: string) => void;
  onParamChange: (name: string, value: unknown) => void;
  onCostModelChange: (id: string) => void;
  onMinNotionalChange: (value: number) => void;
}) {
  const selected = options.policies.find((item) => item.id === policy);
  return (
    <div className="grid gap-3 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-800 sm:grid-cols-2">
      <label className="block text-xs">
        <span className="text-gray-600 dark:text-gray-300">Cost model</span>
        <select
          value={costModel}
          onChange={(event) => onCostModelChange(event.target.value)}
          className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
        >
          {options.cost_models.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs">
        <span className="text-gray-600 dark:text-gray-300">Policy</span>
        <select
          value={policy}
          onChange={(event) => onPolicyChange(event.target.value)}
          className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
        >
          {options.policies.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <p className="text-xs text-gray-500 dark:text-gray-400 sm:col-span-2">
          {selected.description}
        </p>
      )}
      {selected && (
        <PolicyParamFields option={selected} values={policyParams} onChange={onParamChange} />
      )}
      <label className="block text-xs">
        <span className="text-gray-600 dark:text-gray-300">Minimum notional (VND)</span>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          step={100000}
          value={minNotional}
          onChange={(event) => {
            const value = Number(event.target.value);
            onMinNotionalChange(Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0);
          }}
          className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
        />
      </label>
    </div>
  );
}

function PolicyParamFields({
  option,
  values,
  onChange,
}: {
  option: RebalanceOption;
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
}) {
  const properties = Object.entries(option.parameter_schema?.properties ?? {});
  if (properties.length === 0) {
    return null;
  }
  return (
    <>
      {properties.map(([name, property]) => {
        const type = propertyType(property);
        const nullable = (property.anyOf ?? []).some((variant) => variant.type === "null");
        const numeric = type === "integer" || type === "number";
        const label = property.title ?? name;
        const value = values[name];
        return (
          <label key={name} className="block text-xs">
            <span className="text-gray-600 dark:text-gray-300">{label}</span>
            {type === "boolean" ? (
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(event) => onChange(name, event.target.checked)}
                className="mt-1"
              />
            ) : (
              <input
                type={numeric ? "number" : "text"}
                value={value === undefined || value === null ? "" : String(value)}
                min={property.minimum}
                max={property.maximum}
                step={type === "integer" ? 1 : "any"}
                onChange={(event) => {
                  const raw = event.target.value;
                  if (!numeric) {
                    onChange(name, raw);
                    return;
                  }
                  if (raw === "" && nullable) {
                    onChange(name, null);
                    return;
                  }
                  onChange(name, Number(raw));
                }}
                className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
              />
            )}
            {property.description && (
              <span className="mt-0.5 block text-[10px] text-gray-400">
                {property.description}
              </span>
            )}
          </label>
        );
      })}
    </>
  );
}

function RebalanceResults({ result }: { result: RebalanceResult }) {
  const heaviest = Math.max(
    0.0001,
    ...result.positions.map((item) => Math.max(item.current_weight, item.target_weight)),
    result.cash_weight,
    result.target_cash_weight,
  );
  return (
    <div className="space-y-4 rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Order list</h2>
        <button
          type="button"
          onClick={() =>
            downloadTextFile("rebalance-orders.csv", ordersToCsv(result.orders), "text/csv")
          }
          className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:border-blue-400 dark:border-gray-700 dark:text-gray-300 dark:hover:border-blue-400"
        >
          Export orders CSV
        </button>
      </div>

      <CurrentVsTargetChart
        positions={result.positions}
        cashWeight={result.cash_weight}
        targetCashWeight={result.target_cash_weight}
        heaviest={heaviest}
      />

      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
          <thead className="bg-gray-50 text-left text-xs dark:bg-gray-900">
            <tr>
              <th className="px-2 py-1 font-medium">Ticker</th>
              <th className="px-2 py-1 font-medium">Side</th>
              <th className="px-2 py-1 font-medium">Lots</th>
              <th className="px-2 py-1 font-medium">Shares</th>
              <th className="px-2 py-1 font-medium">Ref price</th>
              <th className="px-2 py-1 font-medium">Value</th>
              <th className="px-2 py-1 font-medium">Fee</th>
              <th className="px-2 py-1 font-medium">Tax</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {result.orders.length === 0 ? (
              <tr>
                <td className="px-2 py-2 text-gray-500 dark:text-gray-400" colSpan={8}>
                  No orders: the portfolio is already within the policy&apos;s tolerance.
                </td>
              </tr>
            ) : (
              result.orders.map((order, index) => (
                <tr key={`${order.symbol}-${order.side}-${index}`}>
                  <td className="px-2 py-1 font-medium">{order.symbol}</td>
                  <td className="px-2 py-1">
                    <span
                      className={
                        order.side === "sell"
                          ? "rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                          : "rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"
                      }
                    >
                      {order.side}
                    </span>
                  </td>
                  <td className="px-2 py-1">{order.lots}</td>
                  <td className="px-2 py-1">{order.shares}</td>
                  <td className="px-2 py-1">{formatVnd(order.reference_price)}</td>
                  <td className="px-2 py-1">{formatVnd(order.value)}</td>
                  <td className="px-2 py-1">{formatVnd(order.fee)}</td>
                  <td className="px-2 py-1">{formatVnd(order.tax)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 text-sm sm:grid-cols-3">
        <Stat label="Total cost" value={formatVnd(result.total_cost)} />
        <Stat
          label="Fees + tax"
          value={`${formatVnd(result.total_fee)} + ${formatVnd(result.total_tax)}`}
        />
        <Stat label="Turnover (buys + sells)" value={formatVnd(result.turnover)} />
        <Stat label="Residual cash" value={formatVnd(result.residual_cash)} />
        <Stat label="Total value" value={formatVnd(result.total_value)} />
        <Stat label="Starting cash" value={formatVnd(result.initial_cash)} />
      </div>

      <RebalanceAssumptionsBlock result={result} />

      {result.warnings.length > 0 && (
        <div className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          <ul className="list-disc pl-4">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RebalanceAssumptionsBlock({ result }: { result: RebalanceResult }) {
  const { assumptions } = result;
  return (
    <details className="rounded-md bg-gray-50 p-3 text-xs dark:bg-gray-900">
      <summary className="cursor-pointer font-medium">Assumptions used</summary>
      <dl className="mt-2 grid gap-1 sm:grid-cols-2">
        <Row label="Cost model" value={assumptions.cost_model} />
        <Row label="Policy" value={assumptions.policy} />
        <Row
          label="Brokerage fee"
          value={`${(assumptions.brokerage_fee_rate * 100).toFixed(2)}%`}
        />
        <Row label="Sell tax" value={`${(assumptions.sell_tax * 100).toFixed(2)}%`} />
        <Row label="Minimum notional" value={formatVnd(assumptions.min_notional)} />
        <Row label="Data source" value={assumptions.data_sources.join(", ") || "unknown"} />
        <Row label="Latest close" value={assumptions.latest_date ?? "n/a"} />
        <Row
          label="Prices"
          value={assumptions.prices_adjusted ? "adjusted" : "raw/unadjusted"}
        />
      </dl>
    </details>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-gray-50 p-2 text-sm dark:bg-gray-900">
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
