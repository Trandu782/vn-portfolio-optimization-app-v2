"use client";

/**
 * P&L page: unrealized profit and loss from holdings plus average cost.
 */

import { useEffect, useState } from "react";

import { Card } from "@/components/ui/Card";
import {
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
import { ChevronDownIcon, ChevronUpIcon } from "@/components/ui/Icons";
import { evaluatePnl, type PnLResult } from "@/lib/api";
import { formatVnd, formatWeight } from "@/lib/format";
import { usePortfolio } from "@/lib/portfolio-context";
import { formatPercent } from "@/lib/user-settings";

import { MarketVsCostChart } from "./charts/MarketVsCostChart";
import { PnLBarChart } from "./charts/PnLBarChart";

const DEBOUNCE_MS = 300;

function signedVnd(value: number): string {
  const rounded = Math.round(value);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(rounded).toLocaleString("en-US")} VND`;
}

function signedPercent(fraction: number | null): string {
  if (fraction === null) {
    return "\u2014";
  }
  const percent = fraction * 100;
  const sign = percent > 0 ? "+" : percent < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(percent).toFixed(2)}%`;
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) {
    return "text-fg";
  }
  return value > 0 ? "text-positive" : "text-negative";
}

function StatCard({
  label,
  value,
  sub,
  tone = null,
  primary = false,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: number | null;
  primary?: boolean;
}) {
  return (
    <Card compact className={primary ? "p-4" : "bg-raised/40 p-4"}>
      <p className="text-xs text-fg-muted">{label}</p>
      <p
        className={`mt-1.5 font-mono font-medium tabular-nums ${
          primary ? "text-xl sm:text-2xl leading-none" : "text-base"
        } ${pnlClass(tone)}`}
      >
        {value}
      </p>
      {sub !== undefined && (
        <p className="mt-1.5 font-mono text-xs tabular-nums text-fg-secondary">{sub}</p>
      )}
    </Card>
  );
}

export function PnLCalculator() {
  const { holdings, cash } = usePortfolio();
  const [result, setResult] = useState<PnLResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showWarnings, setShowWarnings] = useState(false);

  useEffect(() => {
    if (holdings.length === 0 && cash === 0) {
      setResult(null);
      return;
    }
    let active = true;
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      evaluatePnl(holdings, cash)
        .then((payload) => {
          if (active) {
            setResult(payload);
          }
        })
        .catch((err: unknown) => {
          if (active) {
            setError(err instanceof Error ? err.message : "P&L calculation failed");
          }
        })
        .finally(() => {
          if (active) {
            setLoading(false);
          }
        });
    }, DEBOUNCE_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [holdings, cash]);

  const warnings = result?.warnings ?? [];

  return (
    <section className="space-y-6">
      {holdings.length === 0 && cash === 0 ? (
        <p className="rounded-xl border border-dashed border-strong p-6 text-sm text-fg-muted">
          Add your holdings and average cost on the Portfolio page to see your profit and loss.
        </p>
      ) : null}

      {loading && result === null && (
        <p className="text-sm text-fg-muted">Calculating profit and loss&hellip;</p>
      )}
      {error && <p className="text-sm text-negative">P&amp;L failed: {error}</p>}

      {result && (
        <>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard
                primary
                label="Total value"
                value={formatVnd(result.summary.total_value)}
              />
              <StatCard
                primary
                label="Unrealized P&L"
                value={signedVnd(result.summary.unrealized_pnl_total)}
                sub={signedPercent(result.summary.unrealized_pnl_pct)}
                tone={result.summary.unrealized_pnl_total}
              />
              <StatCard
                primary
                label="P&L after sell costs"
                value={signedVnd(result.summary.net_of_costs_total)}
                sub={`Fees ${formatVnd(result.summary.sell_fee_total)} · Tax ${formatVnd(
                  result.summary.sell_tax_total,
                )}`}
                tone={result.summary.net_of_costs_total}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard label="Market value" value={formatVnd(result.summary.market_value_total)} />
              <StatCard label="Cost basis" value={formatVnd(result.summary.cost_basis_total)} />
              <StatCard label="Cash" value={formatVnd(result.summary.cash)} />
            </div>
          </div>

          {warnings.length > 0 && (
            <div className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
              <button
                type="button"
                onClick={() => setShowWarnings((prev) => !prev)}
                className="flex w-full items-center justify-between gap-2 text-left font-medium"
              >
                <span>
                  {warnings.length} calculation {warnings.length === 1 ? "note" : "notes"}
                </span>
                {showWarnings ? <ChevronUpIcon size={14} /> : <ChevronDownIcon size={14} />}
              </button>
              {showWarnings && (
                <ul className="mt-2 list-disc space-y-1 pl-4">
                  {warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
            <table className="min-w-full text-sm">
              <thead>
                <tr className={tableHeaderRowClass}>
                  <th className={`${tableHeaderCellClass} sticky left-0 z-10 bg-raised`}>
                    Ticker
                  </th>
                  <th className={`${tableHeaderCellClass} text-right`}>Shares</th>
                  <th className={`${tableHeaderCellClass} text-right`}>Avg cost</th>
                  <th className={tableHeaderCellClass}>Buy date</th>
                  <th className={`${tableHeaderCellClass} text-right`}>Price</th>
                  <th className={`${tableHeaderCellClass} text-right`}>Cost basis</th>
                  <th className={`${tableHeaderCellClass} text-right`}>Market value</th>
                  <th className={`${tableHeaderCellClass} text-right`}>Weight</th>
                  <th className={`${tableHeaderCellClass} text-right`}>P&amp;L</th>
                  <th className={`${tableHeaderCellClass} text-right`}>P&amp;L %</th>
                  <th className={`${tableHeaderCellClass} text-right`}>Share of P&amp;L</th>
                  <th className={`${tableHeaderCellClass} text-right`}>After costs</th>
                  <th className={tableHeaderCellClass}>vs VN-Index</th>
                </tr>
              </thead>
              <tbody>
                {result.holdings.map((holding) => (
                  <tr key={holding.symbol} className={tableRowHoverClass}>
                    <td
                      className={`${tableBodyCellClass} sticky left-0 z-10 bg-surface font-mono font-medium text-fg`}
                    >
                      {holding.symbol}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {holding.shares.toLocaleString("en-US")}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {holding.avg_cost === null ? (
                        <span className="text-fg-muted">&mdash;</span>
                      ) : (
                        formatVnd(holding.avg_cost)
                      )}
                    </td>
                    <td className={`${tableBodyCellClass} font-mono tabular-nums text-fg-secondary`}>
                      {holding.buy_date ?? "\u2014"}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {holding.latest_price === null ? (
                        <span className="text-warn">No price</span>
                      ) : (
                        formatVnd(holding.latest_price)
                      )}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {holding.cost_basis === null ? "\u2014" : formatVnd(holding.cost_basis)}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                    >
                      {formatVnd(holding.market_value)}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                    >
                      {formatWeight(holding.weight)}
                    </td>
                    <td className={`${tableBodyCellClass} text-right font-mono tabular-nums`}>
                      {holding.missing_avg_cost ? (
                        <span className="text-warn">Missing cost</span>
                      ) : (
                        <span className={`font-medium ${pnlClass(holding.unrealized_pnl)}`}>
                          {signedVnd(holding.unrealized_pnl ?? 0)}
                        </span>
                      )}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums ${pnlClass(
                        holding.unrealized_pnl,
                      )}`}
                    >
                      {holding.missing_avg_cost
                        ? "\u2014"
                        : signedPercent(holding.unrealized_pnl_pct)}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                    >
                      {holding.pnl_share === null ? "\u2014" : signedPercent(holding.pnl_share)}
                    </td>
                    <td
                      className={`${tableBodyCellClass} text-right font-mono tabular-nums ${pnlClass(
                        holding.net_of_costs,
                      )}`}
                    >
                      {holding.net_of_costs === null
                        ? "\u2014"
                        : signedVnd(holding.net_of_costs)}
                    </td>
                    <td className={`${tableBodyCellClass} font-mono tabular-nums text-xs`}>
                      {holding.buy_date === null ? (
                        <span className="text-fg-muted">&mdash;</span>
                      ) : typeof holding.price_return === "number" &&
                        typeof holding.benchmark_return === "number" ? (
                        <span>
                          <span className={pnlClass(holding.price_return)}>
                            {signedPercent(holding.price_return)}
                          </span>{" "}
                          <span className="text-fg-muted">
                            vs {signedPercent(holding.benchmark_return)}
                          </span>{" "}
                          {holding.beat_market === true ? (
                            <span className="text-positive">+beat</span>
                          ) : (
                            <span className="text-negative">&minus;lagged</span>
                          )}
                        </span>
                      ) : (
                        <span className="text-fg-muted">not enough data</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <PnLBarChart holdings={result.holdings} />
            <MarketVsCostChart holdings={result.holdings} />
          </div>

          <Card compact className="text-xs text-fg-muted">
            <p className="font-medium text-fg-secondary">Notes and assumptions</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-4">
              <li>
                Realized profit and dividends are not tracked; this is unrealized P&amp;L only.
              </li>
              <li>
                Enter the average cost exactly as your broker app shows it. Brokers already adjust
                it for stock dividends, so no extra adjustment is needed here.
              </li>
              <li>
                Prices are the latest close. Costs appear only in the &ldquo;P&amp;L after sell
                costs&rdquo; figure:{" "}
                <span className="font-mono tabular-nums">
                  {formatPercent(result.assumptions.brokerage_fee_rate)}
                </span>{" "}
                fee plus{" "}
                <span className="font-mono tabular-nums">{formatPercent(result.sell_tax)}</span>{" "}
                sell tax.
              </li>
              <li>
                The &ldquo;vs VN-Index&rdquo; column compares the stock price return since the buy
                date with VN-Index over the same period.
              </li>
            </ul>
          </Card>
        </>
      )}
    </section>
  );
}
