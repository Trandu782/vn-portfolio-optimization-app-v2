"use client";

/**
 * Live valuation table shared by the Portfolio page (and reusable elsewhere).
 *
 * Editable share and average-cost inputs sit next to the API-computed price,
 * market value and weight, so the user sees the effect of an edit as soon as the
 * debounced evaluation returns. Totals include cash.
 */

import type { HoldingValuation, PortfolioEvaluation } from "@/lib/api";
import { formatVnd, formatWeight } from "@/lib/format";
import type { PortfolioHolding } from "@/lib/portfolio";

function parseWhole(value: string): number {
  const parsed = Math.trunc(Number(value));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

interface HoldingsTableProps {
  holdings: PortfolioHolding[];
  valuationBySymbol: Map<string, HoldingValuation>;
  evaluation: PortfolioEvaluation | null;
  loading: boolean;
  onUpdate: (symbol: string, changes: Partial<Omit<PortfolioHolding, "symbol">>) => void;
  onRemove: (symbol: string) => void;
}

export function HoldingsTable({
  holdings,
  valuationBySymbol,
  evaluation,
  loading,
  onUpdate,
  onRemove,
}: HoldingsTableProps) {
  return (
    <div className="space-y-3">
      {evaluation && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">Total value: {formatVnd(evaluation.total_value)}</span>
          <span className="text-gray-600 dark:text-gray-300">
            Holdings {formatVnd(evaluation.market_value_total)} &middot; Cash{" "}
            {formatVnd(evaluation.cash)}
          </span>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Source: {evaluation.freshness.source ?? "n/a"}
            {evaluation.freshness.stale
              ? " · some holdings lack a bar for the latest session (suspension/halt)"
              : ""}
          </span>
          {loading && <span className="text-xs text-gray-500">updating&hellip;</span>}
        </div>
      )}

      {evaluation && evaluation.warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-300">
          {evaluation.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {holdings.length === 0 ? (
        <p className="rounded-lg border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
          No holdings yet. Search for a ticker (or import a CSV/JSON file) to get started.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
            <thead className="bg-gray-50 text-left dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-3 py-2 font-medium">Shares</th>
                <th className="px-3 py-2 font-medium">Avg cost (VND)</th>
                <th className="px-3 py-2 font-medium">Buy date</th>
                <th className="px-3 py-2 font-medium">Price (VND)</th>
                <th className="px-3 py-2 font-medium">Value (VND)</th>
                <th className="px-3 py-2 font-medium">Weight</th>
                <th className="px-3 py-2 font-medium">Notes</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {holdings.map((holding) => {
                const valuation = valuationBySymbol.get(holding.symbol);
                return (
                  <tr key={holding.symbol}>
                    <td className="px-3 py-2 font-medium">
                      {holding.symbol}
                      {holding.shares === 0 && (
                        <span className="ml-2 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-950 dark:text-blue-200">
                          wishlist
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        step={1}
                        aria-label={`Shares for ${holding.symbol}`}
                        value={holding.shares === 0 ? "" : String(holding.shares)}
                        placeholder="0"
                        onChange={(event) =>
                          onUpdate(holding.symbol, { shares: parseWhole(event.target.value) })
                        }
                        className="w-24 rounded-md border border-gray-300 px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        step={1}
                        aria-label={`Average cost for ${holding.symbol}`}
                        value={holding.avg_cost === null ? "" : String(holding.avg_cost)}
                        placeholder="optional"
                        onChange={(event) =>
                          onUpdate(holding.symbol, {
                            avg_cost:
                              event.target.value.trim() === ""
                                ? null
                                : parseWhole(event.target.value),
                          })
                        }
                        className="w-28 rounded-md border border-gray-300 px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="date"
                        aria-label={`Buy date for ${holding.symbol}`}
                        value={holding.buy_date ?? ""}
                        onChange={(event) =>
                          onUpdate(holding.symbol, {
                            buy_date:
                              event.target.value.trim() === "" ? null : event.target.value,
                          })
                        }
                        className="w-36 rounded-md border border-gray-300 px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
                      />
                    </td>
                    <td className="px-3 py-2">
                      {valuation && valuation.latest_price !== null
                        ? formatVnd(valuation.latest_price)
                        : "\u2014"}
                    </td>
                    <td className="px-3 py-2">
                      {valuation ? formatVnd(valuation.market_value) : "\u2014"}
                    </td>
                    <td className="px-3 py-2">
                      {valuation ? formatWeight(valuation.weight) : "\u2014"}
                    </td>
                    <td className="px-3 py-2">
                      {valuation && valuation.warnings.length > 0 ? (
                        <span className="flex flex-wrap gap-1">
                          {valuation.warnings.map((warning) => (
                            <span
                              key={warning}
                              className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                            >
                              {warning}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span className="text-xs text-emerald-600 dark:text-emerald-400">ok</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
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
                );
              })}

            </tbody>
            {evaluation && (
              <tfoot className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <td className="px-3 py-1 font-medium" colSpan={5}>
                    Holdings
                  </td>
                  <td className="px-3 py-1 font-medium">
                    {formatVnd(evaluation.market_value_total)}
                  </td>
                  <td className="px-3 py-1">{formatWeight(1 - evaluation.cash_weight)}</td>
                  <td className="px-3 py-1" colSpan={2} />
                </tr>
                <tr>
                  <td className="px-3 py-1" colSpan={5}>
                    Cash
                  </td>
                  <td className="px-3 py-1">{formatVnd(evaluation.cash)}</td>
                  <td className="px-3 py-1">{formatWeight(evaluation.cash_weight)}</td>
                  <td className="px-3 py-1" colSpan={2} />
                </tr>
                <tr className="font-semibold">
                  <td className="px-3 py-1" colSpan={5}>
                    Total value
                  </td>
                  <td className="px-3 py-1">{formatVnd(evaluation.total_value)}</td>
                  <td className="px-3 py-1">{formatWeight(1)}</td>
                  <td className="px-3 py-1" colSpan={2} />
                </tr>
              </tfoot>
            )}

          </table>
        </div>
      )}

      {loading && !evaluation && (
        <p className="text-sm text-gray-500 dark:text-gray-400">Calculating valuations&hellip;</p>
      )}
    </div>
  );
}
