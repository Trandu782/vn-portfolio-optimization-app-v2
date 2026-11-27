"use client";

import { Card } from "@/components/ui/Card";
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
    <section className="space-y-3">
      <h2 className="flex items-center text-base font-medium text-fg">
        <span>Scorecard</span>
        <InfoTip text="Each card is a ratio category. Green is better than the sector median, red is worse, amber is broadly in line (within 10%) and grey is valuation (neither direction is inherently better)." />
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((group) => (
          <Card key={group.category} compact>
            <h3 className="text-sm font-medium text-fg">{group.categoryLabel}</h3>
            <ul className="mt-2.5 space-y-2">
              {group.ratios.map((ratio) => {
                const verdict = classifyRatio(ratio);
                const tone = verdictTone(verdict);
                const value = ratioDisplayValue(ratio);
                return (
                  <li key={ratio.ratio} className="flex items-center justify-between gap-2 text-sm">
                    <span className="text-fg-secondary">{ratio.label}</span>
                    <span className="flex items-center gap-2">
                      <span
                        className={`font-mono font-medium tabular-nums ${TONE_TEXT_CLASS[tone]}`}
                      >
                        {value}
                      </span>
                      <span
                        title={verdictLabel(verdict)}
                        className={`rounded-md px-2 py-0.5 font-mono text-xs ${TONE_CHIP_CLASS[tone]}`}
                      >
                        {chipLabel(verdict)}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </Card>
        ))}
      </div>
    </section>
  );
}

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
