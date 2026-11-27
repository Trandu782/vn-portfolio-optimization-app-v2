"use client";

/**
 * Rebalance page: turn current holdings plus target weights into a placeable
 * order list.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  inputClass,
  inputCompactClass,
  selectClass,
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
import { DownloadIcon, UploadIcon, XIcon } from "@/components/ui/Icons";
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

const MAX_UPLOAD_BYTES = 1_048_576;

async function readTextFile(
  event: ChangeEvent<HTMLInputElement>,
  onText: (text: string) => void,
  onError: (message: string) => void,
): Promise<void> {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) {
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    onError("CSV import: file is too large (maximum size is 1 MB).");
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

  useEffect(() => {
    if (holdingsPrefilled.current) return;
    if (portfolioHoldings.length === 0 && portfolioCash === 0) return;
    setHoldings(portfolioHoldings.map((holding) => ({ ...holding })));
    setCash(portfolioCash);
    holdingsPrefilled.current = true;
  }, [portfolioHoldings, portfolioCash]);

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
    setNotice("Target weights set to your current weights");
  }, [evaluation]);

  const useOptimizedWeights = useCallback(() => {
    if (chosenWeights === null || Object.keys(chosenWeights).length === 0) {
      setNotice("Run Optimize and press \u201cUse this portfolio\u201d first.");
      return;
    }
    setTargets(targetRowsFromWeights(chosenWeights));
    setTargetsFrom("optimized");
    setNotice("Target weights set to your optimized mix");
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
    setNotice(`Imported ${parsed.holdings.length} holdings`);
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
    setNotice(`Imported ${parsed.rows.length} target weights`);
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
    <section className="space-y-6">
      <p className="max-w-3xl text-sm leading-6 text-fg-secondary">
        Holdings are pre-filled from your{" "}
        <Link href="/portfolio" className="text-accent-ink hover:underline">
          Portfolio
        </Link>{" "}
        and stay editable here. Target weights start from the mix you saved with{" "}
        <Link href="/optimize" className="text-accent-ink hover:underline">
          Optimize
        </Link>{" "}
        and stay editable too; enter them as a percent of total value, and the remainder is cash.
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
        onImportError={setError}
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
        onImportError={setError}
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
        <p className="text-sm text-fg-muted">Loading options&hellip;</p>
      )}

      <p className="rounded-lg border border-hairline bg-raised/50 px-3 py-2.5 text-xs text-fg-secondary">
        Prices are the latest close. Sells are planned before buys, orders round down to
        whole lots, orders below the minimum notional are skipped, and T+2 settlement is
        not modeled in V1 &mdash; check the list against your broker before placing it.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => void handleRun()}
          disabled={running || !options || !ready}
        >
          {running ? "Planning\u2026" : "Plan rebalance"}
        </Button>
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          {holdings.length} holdings &middot; {formatVnd(cash)} cash &middot; {targets.length}{" "}
          targets
        </span>
      </div>

      {error && <p className="text-sm text-negative">{error}</p>}
      {notice && <p className="text-sm text-positive">{notice}</p>}
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
        className={`${inputCompactClass} w-48`}
      />
      {suggestions.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-56 w-56 overflow-auto rounded-lg border border-strong bg-surface text-sm shadow-lg transition-opacity duration-150 ease-unslop">
          {suggestions.map((symbol) => (
            <li key={symbol.code}>
              <button
                type="button"
                onClick={() => pick(symbol.code)}
                className="flex min-h-[40px] w-full items-center justify-between px-3 py-2 text-left transition-colors duration-150 ease-unslop hover:bg-raised"
              >
                <span className="font-mono font-medium text-fg">{symbol.code}</span>
                <span className="ml-2 truncate text-xs text-fg-muted">{symbol.exchange}</span>
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
  onError,
}: {
  label: string;
  onText: (text: string) => void;
  onError: (message: string) => void;
}) {
  return (
    <label className="inline-flex h-10 md:h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-strong bg-raised px-3 text-xs font-medium text-fg transition-colors duration-150 ease-unslop hover:bg-surface">
      <UploadIcon size={14} />
      <span>{label}</span>
      <input
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(event) => void readTextFile(event, onText, onError)}
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
  onImportError,
}: {
  holdings: PortfolioHolding[];
  cash: number;
  universe: SymbolInfo[];
  onCashChange: (cash: number) => void;
  onAdd: (symbol: string) => void;
  onUpdate: (symbol: string, changes: Partial<Omit<PortfolioHolding, "symbol">>) => void;
  onRemove: (symbol: string) => void;
  onImportCsv: (text: string) => void;
  onImportError: (message: string) => void;
}) {
  const existing = useMemo(() => new Set(holdings.map((holding) => holding.symbol)), [holdings]);
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium text-fg">Current holdings</h2>
        <div className="flex flex-wrap items-center gap-2">
          <SymbolSearch
            onPick={onAdd}
            existing={existing}
            universe={universe}
            placeholder="Add holding"
          />
          <UploadLabel
            label="Upload holdings CSV"
            onText={onImportCsv}
            onError={onImportError}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="rebalance-cash" className="block text-sm font-medium text-fg">
          Cash (VND)
        </label>
        <input
          id="rebalance-cash"
          type="number"
          inputMode="numeric"
          min={0}
          step={1000}
          value={cash === 0 ? "" : String(cash)}
          placeholder="0"
          onChange={(event) => onCashChange(parseWhole(event.target.value))}
          className={`${inputClass} w-48 font-mono tabular-nums`}
        />
      </div>

      {holdings.length === 0 ? (
        <p className="text-xs text-fg-muted">No holdings yet; add a ticker above.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-hairline">
          <table className="min-w-full text-sm">
            <thead>
              <tr className={tableHeaderRowClass}>
                <th className={`${tableHeaderCellClass} sticky left-0 z-10 bg-raised`}>
                  Ticker
                </th>
                <th className={tableHeaderCellClass}>Shares</th>
                <th className={tableHeaderCellClass}>Avg cost (VND)</th>
                <th className={tableHeaderCellClass} />
              </tr>
            </thead>
            <tbody>
              {holdings.map((holding) => (
                <tr key={holding.symbol} className={tableRowHoverClass}>
                  <td
                    className={`${tableBodyCellClass} sticky left-0 z-10 bg-surface font-mono font-medium text-fg`}
                  >
                    {holding.symbol}
                  </td>
                  <td className={tableBodyCellClass}>
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
                      className={`${inputCompactClass} w-28 font-mono tabular-nums`}
                    />
                  </td>
                  <td className={tableBodyCellClass}>
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
                      className={`${inputCompactClass} w-32 font-mono tabular-nums`}
                    />
                  </td>
                  <td className={`${tableBodyCellClass} text-right`}>
                    <button
                      type="button"
                      onClick={() => onRemove(holding.symbol)}
                      aria-label={`Remove ${holding.symbol}`}
                      className="inline-flex min-h-[40px] min-w-[40px] items-center justify-center rounded-md text-fg-muted transition-colors duration-150 ease-unslop hover:bg-raised hover:text-negative md:min-h-[28px] md:min-w-[28px]"
                    >
                      <XIcon size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
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
  onImportError,
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
  onImportError: (message: string) => void;
}) {
  const existing = useMemo(() => new Set(targets.map((row) => row.symbol)), [targets]);
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium text-fg">Target weights</h2>
        <div className="flex flex-wrap items-center gap-2">
          <SymbolSearch
            onPick={onAdd}
            existing={existing}
            universe={universe}
            placeholder="Add target"
          />
          <Button
            size="sm"
            onClick={onUseOptimized}
            disabled={!hasOptimizedWeights}
            title={
              hasOptimizedWeights
                ? undefined
                : "Run Optimize and press \u201cUse this portfolio\u201d first."
            }
          >
            Use optimized weights
          </Button>
          <Button size="sm" onClick={onMatchCurrent}>
            Use current weights
          </Button>
          <UploadLabel
            label="Upload target CSV"
            onText={onImportCsv}
            onError={onImportError}
          />
        </div>
      </div>

      {targetsFrom === "optimized" && (
        <p className="text-xs text-positive">
          Started from the optimized mix saved on the Optimize page; edit any value.
        </p>
      )}
      {targetsFrom === "current" && targets.length > 0 && (
        <p className="text-xs text-fg-muted">
          Started from your current portfolio weights; edit any value or use the optimized mix.
        </p>
      )}

      {targets.length === 0 ? (
        <p className="text-xs text-fg-muted">
          No targets yet; add a ticker, use your current weights or the optimized mix.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-hairline">
          <table className="min-w-full text-sm">
            <thead>
              <tr className={tableHeaderRowClass}>
                <th className={`${tableHeaderCellClass} sticky left-0 z-10 bg-raised`}>
                  Ticker
                </th>
                <th className={tableHeaderCellClass}>Target weight (%)</th>
                <th className={tableHeaderCellClass} />
              </tr>
            </thead>
            <tbody>
              {targets.map((row) => (
                <tr key={row.symbol} className={tableRowHoverClass}>
                  <td
                    className={`${tableBodyCellClass} sticky left-0 z-10 bg-surface font-mono font-medium text-fg`}
                  >
                    {row.symbol}
                  </td>
                  <td className={tableBodyCellClass}>
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
                      className={`${inputCompactClass} w-28 font-mono tabular-nums`}
                    />
                  </td>
                  <td className={`${tableBodyCellClass} text-right`}>
                    <button
                      type="button"
                      onClick={() => onRemove(row.symbol)}
                      aria-label={`Remove ${row.symbol}`}
                      className="inline-flex min-h-[40px] min-w-[40px] items-center justify-center rounded-md text-fg-muted transition-colors duration-150 ease-unslop hover:bg-raised hover:text-negative md:min-h-[28px] md:min-w-[28px]"
                    >
                      <XIcon size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="font-mono text-xs tabular-nums text-fg-secondary">
        Total {targetSum.toFixed(1)}% &middot; cash {Math.max(0, 100 - targetSum).toFixed(1)}%
      </p>
    </Card>
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
    <Card className="grid gap-4 sm:grid-cols-2">
      <label className="block space-y-1.5 text-sm">
        <span className="block font-medium text-fg">Cost model</span>
        <select
          value={costModel}
          onChange={(event) => onCostModelChange(event.target.value)}
          className={`${selectClass} w-full`}
        >
          {options.cost_models.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block space-y-1.5 text-sm">
        <span className="block font-medium text-fg">Policy</span>
        <select
          value={policy}
          onChange={(event) => onPolicyChange(event.target.value)}
          className={`${selectClass} w-full`}
        >
          {options.policies.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <p className="text-xs text-fg-muted sm:col-span-2">{selected.description}</p>
      )}
      {selected && (
        <PolicyParamFields option={selected} values={policyParams} onChange={onParamChange} />
      )}
      <label className="block space-y-1.5 text-sm">
        <span className="block font-medium text-fg">Minimum notional (VND)</span>
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
          className={`${inputClass} w-full font-mono tabular-nums`}
        />
      </label>
    </Card>
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
          <label key={name} className="block space-y-1.5 text-sm">
            <span className="block font-medium text-fg">{label}</span>
            {type === "boolean" ? (
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(event) => onChange(name, event.target.checked)}
                className="h-4 w-4 accent-accent"
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
                className={`${inputClass} w-full font-mono tabular-nums`}
              />
            )}
            {property.description && (
              <span className="block text-xs text-fg-muted">{property.description}</span>
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
    <Card className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium text-fg">Order list</h2>
        <Button
          size="sm"
          onClick={() =>
            downloadTextFile("rebalance-orders.csv", ordersToCsv(result.orders), "text/csv")
          }
        >
          <DownloadIcon size={14} />
          Export orders CSV
        </Button>
      </div>

      <CurrentVsTargetChart
        positions={result.positions}
        cashWeight={result.cash_weight}
        targetCashWeight={result.target_cash_weight}
        heaviest={heaviest}
      />

      <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
        <table className="min-w-full text-sm">
          <thead>
            <tr className={tableHeaderRowClass}>
              <th className={`${tableHeaderCellClass} sticky left-0 z-10 bg-raised`}>
                Ticker
              </th>
              <th className={tableHeaderCellClass}>Side</th>
              <th className={`${tableHeaderCellClass} text-right`}>Lots</th>
              <th className={`${tableHeaderCellClass} text-right`}>Shares</th>
              <th className={`${tableHeaderCellClass} text-right`}>Ref price</th>
              <th className={`${tableHeaderCellClass} text-right`}>Value</th>
              <th className={`${tableHeaderCellClass} text-right`}>Fee</th>
              <th className={`${tableHeaderCellClass} text-right`}>Tax</th>
            </tr>
          </thead>
          <tbody>
            {result.orders.length === 0 ? (
              <tr>
                <td className="px-4 py-4 text-fg-muted" colSpan={8}>
                  No orders: the portfolio is already within the policy&apos;s tolerance.
                </td>
              </tr>
            ) : (
              result.orders.map((order, index) => (
                <tr
                  key={`${order.symbol}-${order.side}-${index}`}
                  className={tableRowHoverClass}
                >
                  <td
                    className={`${tableBodyCellClass} sticky left-0 z-10 bg-surface font-mono font-medium text-fg`}
                  >
                    {order.symbol}
                  </td>
                  <td className={tableBodyCellClass}>
                    <Badge tone={order.side === "sell" ? "warn" : "positive"}>
                      {order.side}
                    </Badge>
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {order.lots}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {order.shares.toLocaleString("en-US")}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {formatVnd(order.reference_price)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {formatVnd(order.value)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {formatVnd(order.fee)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {formatVnd(order.tax)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-3 text-sm sm:grid-cols-3">
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
        <div className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          <ul className="list-disc space-y-1 pl-4">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function RebalanceAssumptionsBlock({ result }: { result: RebalanceResult }) {
  const { assumptions } = result;
  return (
    <details className="rounded-lg border border-hairline bg-raised/50 p-3 text-xs">
      <summary className="cursor-pointer font-medium text-fg-secondary">Assumptions used</summary>
      <dl className="mt-2.5 grid gap-2 sm:grid-cols-2">
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
    <div className="rounded-lg border border-hairline bg-raised/50 p-3">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className="mt-1 font-mono font-medium tabular-nums text-fg">{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="text-right font-mono font-medium tabular-nums text-fg">{value}</dd>
    </div>
  );
}
