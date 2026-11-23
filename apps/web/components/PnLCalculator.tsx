"use client";

/**
 * P&L page: unrealized profit and loss from holdings plus average cost.
 *
 * No trade log is involved. The component reads the working portfolio from the
 * shared store, posts it to `/api/v1/pnl/evaluate` (debounced while editing) and
 * renders the summary cards, the per-holding table, a P&L-by-stock bar chart and
 * a market-value-vs-cost chart. Winners and losers are shown with a colour *and*
 * a +/minus sign, and holdings missing an average cost or a price are flagged and
 * excluded from the totals by the API.
 */

import { useEffect, useState } from "react";

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
    return "text-gray-600 dark:text-gray-300";
  }
  return value > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";
}

function Card({
  label,
  value,
  sub,
  tone = null,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: number | null;
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${pnlClass(tone)}`}>{value}</p>
      {sub !== undefined && (
        <p className="text-xs text-gray-500 dark:text-gray-400">{sub}</p>
      )}
    </div>
  );
}

export function PnLCalculator() {
  const { holdings, cash } = usePortfolio();
  const [result, setResult] = useState<PnLResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <p className="rounded-lg border border-dashed border-gray-300 p-4 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
          Add your holdings and average cost on the Portfolio page to see your profit and loss.
        </p>
      ) : null}

      {loading && result === null && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Calculating profit and loss&hellip;
        </p>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400">P&amp;L failed: {error}</p>}

      {result && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Card label="Market value" value={formatVnd(result.summary.market_value_total)} />
            <Card label="Cost basis" value={formatVnd(result.summary.cost_basis_total)} />
            <Card
              label="Unrealized P&L"
              value={signedVnd(result.summary.unrealized_pnl_total)}
              sub={signedPercent(result.summary.unrealized_pnl_pct)}
              tone={result.summary.unrealized_pnl_total}
            />
            <Card
              label="P&L after sell costs"
              value={signedVnd(result.summary.net_of_costs_total)}
              sub={`Fees ${formatVnd(result.summary.sell_fee_total)} · Tax ${formatVnd(
                result.summary.sell_tax_total,
              )}`}
              tone={result.summary.net_of_costs_total}
            />
            <Card label="Cash" value={formatVnd(result.summary.cash)} />
            <Card label="Total value" value={formatVnd(result.summary.total_value)} />
          </div>

          {warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-300">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}

          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
            <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
              <thead className="bg-gray-50 text-left dark:bg-gray-900">
                <tr>
                  <th className="px-3 py-2 font-medium">Ticker</th>
                  <th className="px-3 py-2 font-medium">Shares</th>
                  <th className="px-3 py-2 font-medium">Avg cost</th>
                  <th className="px-3 py-2 font-medium">Buy date</th>
                  <th className="px-3 py-2 font-medium">Price</th>
                  <th className="px-3 py-2 font-medium">Cost basis</th>
                  <th className="px-3 py-2 font-medium">Market value</th>
                  <th className="px-3 py-2 font-medium">Weight</th>
                  <th className="px-3 py-2 font-medium">P&amp;L</th>
                  <th className="px-3 py-2 font-medium">P&amp;L %</th>
                  <th className="px-3 py-2 font-medium">Share of P&amp;L</th>
                  <th className="px-3 py-2 font-medium">After costs</th>
                  <th className="px-3 py-2 font-medium">vs VN-Index</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {result.holdings.map((holding) => (
                  <tr key={holding.symbol}>
                    <td className="px-3 py-2 font-medium">{holding.symbol}</td>
                    <td className="px-3 py-2">{holding.shares.toLocaleString("en-US")}</td>
                    <td className="px-3 py-2">
                      {holding.avg_cost === null ? (
                        <span className="text-gray-400">&mdash;</span>
                      ) : (
                        formatVnd(holding.avg_cost)
                      )}
                    </td>
                    <td className="px-3 py-2">{holding.buy_date ?? "\u2014"}</td>
                    <td className="px-3 py-2">
                      {holding.latest_price === null ? (
                        <span className="text-amber-600 dark:text-amber-400">No price</span>
                      ) : (
                        formatVnd(holding.latest_price)
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {holding.cost_basis === null ? "\u2014" : formatVnd(holding.cost_basis)}
                    </td>
                    <td className="px-3 py-2">{formatVnd(holding.market_value)}</td>
                    <td className="px-3 py-2">{formatWeight(holding.weight)}</td>
                    <td className="px-3 py-2">
                      {holding.missing_avg_cost ? (
                        <span className="text-amber-600 dark:text-amber-400">
                          Enter your average cost
                        </span>
                      ) : (
                        <span className={`font-medium ${pnlClass(holding.unrealized_pnl)}`}>
                          {signedVnd(holding.unrealized_pnl ?? 0)}
                        </span>
                      )}
                    </td>
                    <td className={`px-3 py-2 ${pnlClass(holding.unrealized_pnl)}`}>
                      {holding.missing_avg_cost
                        ? "\u2014"
                        : signedPercent(holding.unrealized_pnl_pct)}
                    </td>
                    <td className={`px-3 py-2 ${pnlClass(holding.pnl_share)}`}>
                      {holding.pnl_share === null ? "\u2014" : signedPercent(holding.pnl_share)}
                    </td>
                    <td className={`px-3 py-2 ${pnlClass(holding.net_of_costs)}`}>
                      {holding.net_of_costs === null
                        ? "\u2014"
                        : signedVnd(holding.net_of_costs)}
                    </td>
                    <td className="px-3 py-2">
                      {holding.buy_date === null ? (
                        <span className="text-gray-400">&mdash;</span>
                      ) : typeof holding.price_return === "number" &&
                        typeof holding.benchmark_return === "number" ? (
                        <span>
                          <span className={pnlClass(holding.price_return)}>
                            {signedPercent(holding.price_return)}
                          </span>{" "}
                          <span className="text-gray-500 dark:text-gray-400">
                            vs {signedPercent(holding.benchmark_return)}
                          </span>{" "}
                          {holding.beat_market === true ? (
                            <span className="text-emerald-600 dark:text-emerald-400">+beat</span>
                          ) : (
                            <span className="text-red-600 dark:text-red-400">&minus;lagged</span>
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-400">not enough data</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <PnLBarChart holdings={result.holdings} />
            <MarketVsCostChart holdings={result.holdings} />
          </div>

          <div className="rounded-lg border border-gray-200 p-3 text-xs text-gray-500 dark:border-gray-800 dark:text-gray-400">
            <p className="font-medium text-gray-600 dark:text-gray-300">Notes and assumptions</p>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              <li>
                Realized profit and dividends are not tracked; this is unrealized P&amp;L only.
              </li>
              <li>
                Enter the average cost exactly as your broker app shows it. Brokers already adjust
                it for stock dividends, so no extra adjustment is needed here.
              </li>
              <li>
                Prices are the latest close. Costs appear only in the &ldquo;P&amp;L after sell
                costs&rdquo; figure: {formatPercent(result.assumptions.brokerage_fee_rate)} fee plus{" "}
                {formatPercent(result.sell_tax)} sell tax.
              </li>
              <li>
                The &ldquo;vs VN-Index&rdquo; column compares the stock price return since the buy
                date with VN-Index over the same period.
              </li>
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
