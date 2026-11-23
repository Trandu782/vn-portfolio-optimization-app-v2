"use client";

/**
 * Detail table for one ticker's ratios versus its sector (docs/V2_SPEC.md 3.3).
 *
 * Columns: ratio, ticker value, sector median, winsorized mean, percentile rank and
 * N. The ticker value is coloured direction-aware (higher- or lower-is-better,
 * valuation neutral) and shows "n/m" where a non-positive valuation multiple is not
 * meaningful. Every numeric column header carries the reporting period, and a row
 * with fewer than five peers is flagged "insufficient peers (N < 5)".
 */

import type { FundamentalsComparison } from "@/lib/api";
import {
  formatPercentileRank,
  formatRatioValue,
  INSUFFICIENT_PEERS_LABEL,
  MIN_PEERS,
  ratioDisplayValue,
  reportingPeriodLabel,
  TONE_CHIP_CLASS,
  TONE_TEXT_CLASS,
  classifyRatio,
  verdictTone,
} from "@/lib/fundamentals";

import { InfoTip } from "./InfoTip";

function directionHint(direction: string): string {
  if (direction === "higher") return "Higher is better";
  if (direction === "lower") return "Lower is better";
  return "Valuation: neither direction is inherently better";
}

export function FundamentalsTable({
  comparison,
}: {
  comparison: FundamentalsComparison;
}) {
  const ratios = comparison.ratios ?? [];
  const periodLabel = reportingPeriodLabel(comparison.period, comparison.period_type);
  const periodShort = `${comparison.period} · ${comparison.period_type.toUpperCase()}`;
  const anyThin = ratios.some((ratio) => (ratio.peers?.n ?? 0) < MIN_PEERS);

  if (ratios.length === 0) {
    return null;
  }

  const periodSub = (
    <span className="block text-[10px] font-normal text-gray-500 dark:text-gray-400">
      {periodShort}
    </span>
  );

  return (
    <section className="space-y-2">
      <h2 className="flex items-center text-lg font-semibold">
        Detail
        <InfoTip text="Compare each ratio with the sector median and the winsorized mean (the mean with the 5th/95th percentiles pulled in so one outlier cannot distort it). The percentile rank says how many peers this ticker beats." />
      </h2>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        All values are for {periodLabel}. The median is the primary comparison; the
        winsorized mean is shown for reference.
      </p>
      {anyThin && (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          Some ratios have {INSUFFICIENT_PEERS_LABEL}: the ticker&apos;s own value and the
          sector figures are shown, but treat the rank with caution.
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
          <thead className="bg-gray-50 text-left dark:bg-gray-900">
            <tr>
              <th className="px-3 py-2 font-medium">Ratio</th>
              <th className="px-3 py-2 font-medium">
                Ticker value
                {periodSub}
              </th>
              <th className="px-3 py-2 font-medium">
                Sector median
                {periodSub}
              </th>
              <th className="px-3 py-2 font-medium">
                Winsorized mean
                {periodSub}
              </th>
              <th className="px-3 py-2 font-medium">
                Percentile rank
                {periodSub}
              </th>
              <th className="px-3 py-2 font-medium">N</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {ratios.map((ratio) => {
              const peers = ratio.peers;
              const n = peers?.n ?? 0;
              const thin = n < MIN_PEERS;
              const verdict = classifyRatio(ratio);
              const tone = verdictTone(verdict);
              return (
                <tr key={ratio.ratio}>
                  <td className="px-3 py-2">
                    <span className="font-medium">{ratio.label}</span>
                    <InfoTip text={directionHint(ratio.direction)} />
                  </td>
                  <td className={`px-3 py-2 font-medium tabular-nums ${TONE_TEXT_CLASS[tone]}`}>
                    {ratioDisplayValue(ratio)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-gray-700 dark:text-gray-300">
                    {formatRatioValue(peers?.median, ratio.is_percentage)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-gray-700 dark:text-gray-300">
                    {formatRatioValue(peers?.winsorized_mean, ratio.is_percentage)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-gray-700 dark:text-gray-300">
                    {formatPercentileRank(peers?.percentile_rank)}
                  </td>
                  <td className="px-3 py-2">
                    <span className="tabular-nums">{n}</span>
                    {thin && (
                      <span
                        title={INSUFFICIENT_PEERS_LABEL}
                        className={`ml-2 rounded-full px-2 py-0.5 text-[11px] ${TONE_CHIP_CLASS.warn}`}
                      >
                        N &lt; 5
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
