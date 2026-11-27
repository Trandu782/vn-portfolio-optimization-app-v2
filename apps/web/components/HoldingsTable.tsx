"use client";

/**
 * Live valuation table shared by the Portfolio page (and reusable elsewhere).
 */

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import {
  inputCompactClass,
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
import { ChevronDownIcon, ChevronUpIcon, XIcon } from "@/components/ui/Icons";
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
  const [showWarnings, setShowWarnings] = useState(false);

  return (
    <div className="space-y-3">
      {evaluation && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-mono font-medium tabular-nums text-fg">
            Total value: {formatVnd(evaluation.total_value)}
          </span>
          <span className="font-mono tabular-nums text-fg-secondary">
            Holdings {formatVnd(evaluation.market_value_total)} &middot; Cash{" "}
            {formatVnd(evaluation.cash)}
          </span>
          <span className="font-mono text-xs tabular-nums text-fg-muted">
            Source: {evaluation.freshness.source ?? "n/a"}
            {evaluation.freshness.stale
              ? " · some holdings lack a bar for the latest session"
              : ""}
          </span>
          {loading && <span className="text-xs text-fg-muted">Updating&hellip;</span>}
        </div>
      )}

      {evaluation && evaluation.warnings.length > 0 && (
        <div className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          <button
            type="button"
            onClick={() => setShowWarnings((prev) => !prev)}
            className="flex w-full items-center justify-between gap-2 text-left font-medium"
          >
            <span>
              {evaluation.warnings.length} data{" "}
              {evaluation.warnings.length === 1 ? "note" : "notes"}
            </span>
            {showWarnings ? <ChevronUpIcon size={14} /> : <ChevronDownIcon size={14} />}
          </button>
          {showWarnings && (
            <ul className="mt-2 list-disc space-y-1 pl-4">
              {evaluation.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {holdings.length === 0 ? (
        <p className="rounded-xl border border-dashed border-strong p-6 text-sm text-fg-muted">
          No holdings yet. Search for a ticker (or import a CSV/JSON file) to get started.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
          <table className="min-w-full text-sm">
            <thead>
              <tr className={tableHeaderRowClass}>
                <th className={`${tableHeaderCellClass} sticky left-0 z-10 bg-raised`}>
                  Ticker
                </th>
                <th className={tableHeaderCellClass}>Shares</th>
                <th className={tableHeaderCellClass}>Avg cost (VND)</th>
                <th className={tableHeaderCellClass}>Buy date</th>
                <th className={`${tableHeaderCellClass} text-right`}>Price (VND)</th>
                <th className={`${tableHeaderCellClass} text-right`}>Value (VND)</th>
                <th className={`${tableHeaderCellClass} text-right`}>Weight</th>
                <th className={tableHeaderCellClass}>Status</th>
                <th className={tableHeaderCellClass} />
              </tr>
            </thead>
            <tbody>
              {holdings.map((holding) => {
                const valuation = valuationBySymbol.get(holding.symbol);
                const hasWarnings = Boolean(valuation && valuation.warnings.length > 0);
                return (
                  <tr key={holding.symbol} className={tableRowHoverClass}>
                    <td
                      className={`${tableBodyCellClass} sticky left-0 z-10 bg-surface font-mono font-medium text-fg`}
                    >
                      <div className="flex items-center gap-2">
                        <span>{holding.symbol}</span>
                        {holding.shares === 0 && <Badge tone="accent">wishlist</Badge>}
                      </div>
                    </td>
                    <td className={tableBodyCellClass}>
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
                        className={`${inputCompactClass} w-24 font-mono tabular-nums`}
                      />
                    </td>
                    <td className={tableBodyCellClass}>
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
                        className={`${inputCompactClass} w-28 font-mono tabular-nums`}
                      />
                    </td>
                    <td className={tableBodyCellClass}>
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
                        className={`${inputCompactClass} w-36 font-mono tabular-nums`}
                      />
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {valuation && valuation.latest_price !== null
                        ? formatVnd(valuation.latest_price)
                        : "\u2014"}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {valuation ? formatVnd(valuation.market_value) : "\u2014"}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                    >
                      {valuation ? formatWeight(valuation.weight) : "\u2014"}
                    </td>
                    <td className={tableBodyCellClass}>
                      {hasWarnings ? (
                        <span
                          title={valuation!.warnings.join(" · ")}
                          className="inline-flex cursor-help items-center gap-1.5 text-xs text-warn"
                        >
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn"
                            aria-hidden="true"
                          />
                          <span>Stale</span>
                        </span>
                      ) : (
                        <span className="text-xs text-positive">ok</span>
                      )}
                    </td>
                    <td className={`${tableBodyCellClass} text-right`}>
                      <button
                        type="button"
                        onClick={() => onRemove(holding.symbol)}
                        aria-label={`Remove ${holding.symbol}`}
                        className="inline-flex min-h-[40px] min-w-[40px] items-center justify-center rounded-md text-fg-muted transition-colors duration-150 ease-unslop hover:bg-raised hover:text-negative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent md:min-h-[28px] md:min-w-[28px]"
                      >
                        <XIcon size={15} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {evaluation && (
              <tfoot className="border-t border-hairline bg-raised text-sm">
                <tr>
                  <td className="px-4 py-2.5 font-medium text-fg" colSpan={5}>
                    Holdings
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono font-medium tabular-nums whitespace-nowrap text-fg">
                    {formatVnd(evaluation.market_value_total)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums whitespace-nowrap text-fg-secondary">
                    {formatWeight(1 - evaluation.cash_weight)}
                  </td>
                  <td className="px-4 py-2.5" colSpan={2} />
                </tr>
                <tr className="border-t border-hairline">
                  <td className="px-4 py-2 text-fg-secondary" colSpan={5}>
                    Cash
                  </td>
                  <td className="px-4 py-2 text-right font-mono tabular-nums whitespace-nowrap text-fg-secondary">
                    {formatVnd(evaluation.cash)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono tabular-nums whitespace-nowrap text-fg-secondary">
                    {formatWeight(evaluation.cash_weight)}
                  </td>
                  <td className="px-4 py-2" colSpan={2} />
                </tr>
                <tr className="border-t border-hairline font-medium">
                  <td className="px-4 py-2.5 text-fg" colSpan={5}>
                    Total value
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums whitespace-nowrap text-fg">
                    {formatVnd(evaluation.total_value)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums whitespace-nowrap text-fg">
                    {formatWeight(1)}
                  </td>
                  <td className="px-4 py-2.5" colSpan={2} />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      {loading && !evaluation && (
        <p className="text-sm text-fg-muted">Calculating valuations&hellip;</p>
      )}
    </div>
  );
}
