"use client";

/**
 * One ticker's full fundamentals view (docs/V2_SPEC.md section 3.3): the reporting
 * period / provider / data-as-of metadata, the scorecard cards, the detail table and
 * the sector-distribution box plot. It is shared by the Fundamentals sub-tab and the
 * ticker drawer, so both entry points show exactly the same content.
 */

import { useMemo, useState } from "react";

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
    <div className="space-y-5">
      <dl className="grid gap-2 rounded-lg bg-gray-50 p-3 text-xs text-gray-600 sm:grid-cols-2 lg:grid-cols-3 dark:bg-gray-900 dark:text-gray-300">
        <div>
          <dt className="font-medium">Ticker</dt>
          <dd>
            {comparison.symbol} &middot; {comparison.sector ?? "unknown sector"}
          </dd>
        </div>
        <div>
          <dt className="font-medium">Peer group</dt>
          <dd>{groupLabel(comparison.ratio_group)}</dd>
        </div>
        <div>
          <dt className="font-medium">Reporting period</dt>
          <dd>{reportingPeriodLabel(comparison.period, comparison.period_type)}</dd>
        </div>
        <div>
          <dt className="font-medium">Provider</dt>
          <dd>{comparison.provider ?? "unknown"}</dd>
        </div>
        <div>
          <dt className="font-medium">Data as of</dt>
          <dd>{comparison.data_as_of ?? "unknown"}</dd>
        </div>
        <div>
          <dt className="font-medium">Peer set</dt>
          <dd>{VARIANT_LABELS[comparison.variant] ?? comparison.variant}</dd>
        </div>
      </dl>

      <FundamentalsScorecard groups={groups} />
      <FundamentalsTable comparison={comparison} />

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Sector distribution</h2>
          <label className="ml-auto flex items-center gap-2 text-sm">
            <span className="text-gray-600 dark:text-gray-300">Ratio</span>
            <select
              value={effectiveKey}
              onChange={(event) => setSelectedKey(event.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
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
          <p className="rounded-lg border border-gray-200 p-4 text-sm text-gray-500 dark:border-gray-800 dark:text-gray-400">
            No peer distribution to plot for this ratio yet (insufficient peers or no
            values). The ticker&apos;s own value is still shown in the table above.
          </p>
        )}
      </section>

      <p className="rounded-md bg-gray-50 p-2 text-xs text-gray-600 dark:bg-gray-900 dark:text-gray-300">
        Banks, financial services and insurers are only compared with their own group,
        never with non-financial companies. Decision support only; not financial advice.
      </p>
    </div>
  );
}
