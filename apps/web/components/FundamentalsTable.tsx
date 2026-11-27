"use client";

import {
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
import type { FundamentalsComparison } from "@/lib/api";
import {
  classifyRatio,
  formatPercentileRank,
  formatRatioValue,
  INSUFFICIENT_PEERS_LABEL,
  MIN_PEERS,
  ratioDisplayValue,
  reportingPeriodLabel,
  TONE_CHIP_CLASS,
  TONE_TEXT_CLASS,
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
    <span className="block font-mono text-xs font-normal text-fg-muted">{periodShort}</span>
  );

  return (
    <section className="space-y-3">
      <h2 className="flex items-center text-base font-medium text-fg">
        <span>Detail</span>
        <InfoTip text="Compare each ratio with the sector median and the winsorized mean (the mean with the 5th/95th percentiles pulled in so one outlier cannot distort it). The percentile rank says how many peers this ticker beats." />
      </h2>
      <p className="text-xs text-fg-muted">
        All values are for {periodLabel}. The median is the primary comparison; the
        winsorized mean is shown for reference.
      </p>
      {anyThin && (
        <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          Some ratios have {INSUFFICIENT_PEERS_LABEL}: the ticker&apos;s own value and the
          sector figures are shown, but treat the rank with caution.
        </p>
      )}

      <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
        <table className="min-w-full text-sm">
          <thead>
            <tr className={tableHeaderRowClass}>
              <th className={tableHeaderCellClass}>Ratio</th>
              <th className={`${tableHeaderCellClass} text-right`}>
                Ticker value
                {periodSub}
              </th>
              <th className={`${tableHeaderCellClass} text-right`}>
                Sector median
                {periodSub}
              </th>
              <th className={`${tableHeaderCellClass} text-right`}>
                Winsorized mean
                {periodSub}
              </th>
              <th className={`${tableHeaderCellClass} text-right`}>
                Percentile rank
                {periodSub}
              </th>
              <th className={`${tableHeaderCellClass} text-right`}>N</th>
            </tr>
          </thead>
          <tbody>
            {ratios.map((ratio) => {
              const peers = ratio.peers;
              const n = peers?.n ?? 0;
              const thin = n < MIN_PEERS;
              const verdict = classifyRatio(ratio);
              const tone = verdictTone(verdict);
              return (
                <tr key={ratio.ratio} className={tableRowHoverClass}>
                  <td className={tableBodyCellClass}>
                    <span className="font-medium text-fg">{ratio.label}</span>
                    <InfoTip text={directionHint(ratio.direction)} />
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono font-medium tabular-nums ${TONE_TEXT_CLASS[tone]}`}
                  >
                    {ratioDisplayValue(ratio)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {formatRatioValue(peers?.median, ratio.is_percentage)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {formatRatioValue(peers?.winsorized_mean, ratio.is_percentage)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {formatPercentileRank(peers?.percentile_rank)}
                  </td>
                  <td className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}>
                    <span>{n}</span>
                    {thin && (
                      <span
                        title={INSUFFICIENT_PEERS_LABEL}
                        className={`ml-2 rounded-md px-2 py-0.5 text-xs ${TONE_CHIP_CLASS.warn}`}
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
