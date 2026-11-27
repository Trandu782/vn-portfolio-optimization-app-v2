"use client";

import { useMemo, useState } from "react";

import { Card } from "@/components/ui/Card";
import { selectClass } from "@/components/ui/Field";
import type { FundamentalsComparison } from "@/lib/api";
import {
  boxPlotStats,
  classifyRatio,
  groupByCategory,
  groupLabel,
  reportingPeriodLabel,
} from "@/lib/fundamentals";

import { FundamentalsScorecard } from "./FundamentalsScorecard";
import { FundamentalsTable } from "./FundamentalsTable";
import { RatioBoxPlot } from "./charts/RatioBoxPlot";

const VARIANT_LABELS: Record<string, string> = {
  all: "All peers in the sector",
  liquidity: "Same sector, active liquidity preset",
  vn100: "Same sector, VN100 members",
};

export function FundamentalsPanel({
  comparison,
}: {
  comparison: FundamentalsComparison;
}) {
  const ratios = useMemo(() => comparison.ratios ?? [], [comparison.ratios]);
  const groups = useMemo(() => groupByCategory(ratios), [ratios]);
  const plottable = useMemo(
    () => ratios.filter((ratio) => (ratio.peers?.n ?? 0) > 0),
    [ratios],
  );
  const defaultKey =
    plottable.find((ratio) => ratio.ratio === "roe")?.ratio ??
    plottable[0]?.ratio ??
    ratios[0]?.ratio ??
    "";
  const [selectedKey, setSelectedKey] = useState(defaultKey);
  const effectiveKey = plottable.some((ratio) => ratio.ratio === selectedKey)
    ? selectedKey
    : defaultKey;
  const selected = ratios.find((ratio) => ratio.ratio === effectiveKey);
  const stats = selected ? boxPlotStats(selected.peers) : null;
  const verdict = selected ? classifyRatio(selected) : "not_meaningful";

  return (
    <div className="space-y-6">
      <dl className="grid gap-3 rounded-xl border border-hairline bg-raised/50 p-4 text-xs text-fg-secondary sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="font-medium text-fg">Ticker</dt>
          <dd className="mt-0.5 font-mono">
            {comparison.symbol} &middot; {comparison.sector ?? "unknown sector"}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-fg">Peer group</dt>
          <dd className="mt-0.5">{groupLabel(comparison.ratio_group)}</dd>
        </div>
        <div>
          <dt className="font-medium text-fg">Reporting period</dt>
          <dd className="mt-0.5 font-mono tabular-nums">
            {reportingPeriodLabel(comparison.period, comparison.period_type)}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-fg">Provider</dt>
          <dd className="mt-0.5 font-mono">{comparison.provider ?? "unknown"}</dd>
        </div>
        <div>
          <dt className="font-medium text-fg">Data as of</dt>
          <dd className="mt-0.5 font-mono tabular-nums">
            {comparison.data_as_of ?? "unknown"}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-fg">Peer set</dt>
          <dd className="mt-0.5">{VARIANT_LABELS[comparison.variant] ?? comparison.variant}</dd>
        </div>
      </dl>

      <FundamentalsScorecard groups={groups} />
      <FundamentalsTable comparison={comparison} />

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-base font-medium text-fg">Sector distribution</h2>
          <label className="ml-auto flex items-center gap-2 text-sm">
            <span className="text-fg-secondary">Ratio</span>
            <select
              value={effectiveKey}
              onChange={(event) => setSelectedKey(event.target.value)}
              className={selectClass}
            >
              {ratios.map((ratio) => (
                <option key={ratio.ratio} value={ratio.ratio}>
                  {ratio.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {selected && stats ? (
          <RatioBoxPlot
            label={selected.label}
            stats={stats}
            tickerValue={selected.value ?? null}
            isPercentage={selected.is_percentage}
            verdict={verdict}
            n={selected.peers?.n ?? 0}
          />
        ) : (
          <Card className="text-sm text-fg-muted">
            No peer distribution to plot for this ratio yet (insufficient peers or no
            values). The ticker&apos;s own value is still shown in the table above.
          </Card>
        )}
      </section>

      <p className="rounded-lg border border-hairline bg-raised/50 px-3 py-2.5 text-xs text-fg-muted">
        Banks, financial services and insurers are only compared with their own group,
        never with non-financial companies. Decision support only; not financial advice.
      </p>
    </div>
  );
}
