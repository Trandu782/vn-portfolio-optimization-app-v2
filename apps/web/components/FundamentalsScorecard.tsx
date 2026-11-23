"use client";

/**
 * Scorecard cards by ratio category (docs/V2_SPEC.md section 3.3).
 *
 * One card per category that has an available ratio (Profitability, Solvency,
 * Liquidity, Valuation, Asset quality), each listing the ticker's value and a
 * direction-aware "better / similar / worse than the sector median" chip. Only
 * categories the API returns for the ticker's peer group are shown, so a bank sees
 * ROE/ROA/NPL and a general company sees margins and liquidity.
 */

import {
  classifyRatio,
  ratioDisplayValue,
  TONE_CHIP_CLASS,
  TONE_TEXT_CLASS,
  verdictLabel,
  verdictTone,
  type RatioCategoryGroup,
} from "@/lib/fundamentals";

import { InfoTip } from "./InfoTip";

export function FundamentalsScorecard({
  groups,
}: {
  groups: RatioCategoryGroup[];
}) {
  if (groups.length === 0) {
    return null;
  }
  return (
    <section className="space-y-2">
      <h2 className="flex items-center text-lg font-semibold">
        Scorecard
        <InfoTip text="Each card is a ratio category. Green is better than the sector median, red is worse, amber is broadly in line (within 10%) and grey is valuation (neither direction is inherently better)." />
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((group) => (
          <div
            key={group.category}
            className="rounded-lg border border-gray-200 p-3 dark:border-gray-800"
          >
            <h3 className="text-sm font-semibold">{group.categoryLabel}</h3>
            <ul className="mt-2 space-y-1.5">
              {group.ratios.map((ratio) => {
                const verdict = classifyRatio(ratio);
                const tone = verdictTone(verdict);
                const value = ratioDisplayValue(ratio);
                return (
                  <li key={ratio.ratio} className="flex items-center justify-between gap-2 text-sm">
                    <span className="text-gray-600 dark:text-gray-300">{ratio.label}</span>
                    <span className="flex items-center gap-2">
                      <span className={`font-medium tabular-nums ${TONE_TEXT_CLASS[tone]}`}>
                        {value}
                      </span>
                      <span
                        title={verdictLabel(verdict)}
                        className={`rounded-full px-2 py-0.5 text-[11px] ${TONE_CHIP_CLASS[tone]}`}
                      >
                        {chipLabel(verdict)}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

/** A short chip label; the full wording lives in the tooltip/title. */
function chipLabel(verdict: ReturnType<typeof classifyRatio>): string {
  switch (verdict) {
    case "better":
      return "better";
    case "similar":
      return "similar";
    case "worse":
      return "worse";
    case "insufficient_peers":
      return "N < 5";
    default:
      return "n/m";
  }
}
