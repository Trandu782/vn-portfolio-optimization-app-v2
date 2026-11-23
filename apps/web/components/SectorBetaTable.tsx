"use client";

/**
 * Sector Beta & Performance table (docs/V2_SPEC.md section 3.2).
 *
 * Sortable columns, a reliability badge, greyed `insufficient` rows, a "cap off" marker
 * for sectors where the single-stock cap was infeasible, and a checkbox per row: every
 * published (ok) sector is ticked by default and insufficient rows are not selectable.
 * The selection feeds "Send sectors to Optimizer".
 */

import { formatPercent, formatSignedPercent } from "@/lib/chart-theme";
import {
  isRowGreyed,
  rowBadge,
  type SectorRow,
  type SectorSortKey,
  type SortDirection,
} from "@/lib/sector-analysis";

function Tip({ text }: { text: string }) {
  return (
    <span
      title={text}
      aria-label={text}
      className="ml-1 cursor-help rounded-full border border-gray-300 px-1 text-[10px] leading-4 text-gray-500 dark:border-gray-600 dark:text-gray-400"
    >
      ?
    </span>
  );
}

const COLUMNS: Array<{ key: SectorSortKey; label: string; tip: string }> = [
  { key: "name", label: "Sector", tip: "ICB level-2 sector name." },
  { key: "period_return", label: "Period", tip: "Return of the sector index over the window." },
  { key: "excess_return", label: "Excess", tip: "Sector return minus the benchmark's over the window." },
  { key: "beta", label: "Beta", tip: "Sensitivity to the benchmark; 1 means it moves with it." },
  { key: "r_squared", label: "R\u00b2", tip: "How much of the sector's move the benchmark explains (0-1)." },
  { key: "annualized_volatility", label: "Volatility", tip: "Annualised standard deviation of daily returns." },
  { key: "constituent_count", label: "Constituents", tip: "Stocks in the sector index; default-excluded names are not counted." },
];

function percentCell(value: number | null, signed: boolean): string {
  if (value === null) return "\u2014";
  return signed ? formatSignedPercent(value / 100) : formatPercent(value / 100);
}

function numberCell(value: number | null, digits: number): string {
  return value === null ? "\u2014" : value.toFixed(digits);
}

export function SectorBetaTable({
  rows,
  selected,
  onToggle,
  sortKey,
  sortDirection,
  onSort,
}: {
  rows: SectorRow[];
  selected: Set<string>;
  onToggle: (name: string) => void;
  sortKey: SectorSortKey;
  sortDirection: SortDirection;
  onSort: (key: SectorSortKey) => void;
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <h2 className="text-lg font-semibold">Sector beta &amp; performance</h2>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
        How each sector moved and how sensitive it is to the benchmark. Beta above 1 means it
        swings more than the market; excess return is the period return minus the benchmark&apos;s.
        Tick the sectors to send to the Optimizer.
      </p>

      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
          <caption className="sr-only">
            Sortable sector performance and risk metrics with a send-to-Optimizer checkbox.
          </caption>
          <thead className="bg-gray-50 text-left dark:bg-gray-900">
            <tr>
              <th scope="col" className="px-2 py-2 font-medium">
                <span className="sr-only">Send to Optimizer</span>
              </th>
              {COLUMNS.map((column) => (
                <th key={column.key} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">
                  <button
                    type="button"
                    onClick={() => onSort(column.key)}
                    className="inline-flex items-center gap-1 hover:text-blue-600 dark:hover:text-blue-400"
                    aria-label={`Sort by ${column.label}`}
                  >
                    {column.label}
                    {sortKey === column.key ? (sortDirection === "asc" ? " \u25b2" : " \u25bc") : ""}
                  </button>
                  <Tip text={column.tip} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {rows.map((row) => {
              const greyed = isRowGreyed(row);
              const badge = rowBadge(row);
              return (
                <tr key={row.name} className={greyed ? "opacity-50" : ""}>
                  <td className="px-2 py-2">
                    <input
                      type="checkbox"
                      disabled={greyed}
                      checked={!greyed && selected.has(row.name)}
                      onChange={() => onToggle(row.name)}
                      aria-label={`Send ${row.name} to the Optimizer`}
                    />
                  </td>
                  <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-medium">
                    {row.name}
                    {badge && (
                      <span
                        className={
                          badge.tone === "warning"
                            ? "ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                            : "ml-2 rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:bg-gray-700 dark:text-gray-200"
                        }
                      >
                        {badge.label}
                      </span>
                    )}
                    {row.capOff && (
                      <span
                        title={row.capOffReason ?? "The single-stock cap could not be applied."}
                        className="ml-2 rounded-full border border-gray-300 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:border-gray-600 dark:text-gray-300"
                      >
                        cap off
                      </span>
                    )}
                  </th>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">{percentCell(row.periodReturn, true)}</td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">{percentCell(row.excessReturn, true)}</td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">{numberCell(row.beta, 2)}</td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">{numberCell(row.rSquared, 2)}</td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">{percentCell(row.volatility, false)}</td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">
                    {row.constituentCount}
                    {row.defaultExcludedCount > 0 && (
                      <span className="ml-1 text-xs text-gray-500 dark:text-gray-400">
                        (-{row.defaultExcludedCount})
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        A sector needs at least 3 constituents to publish an index; thinner sectors are greyed
        and cannot be sent. (-n) marks constituents dropped by the default adjustment checks.
      </p>
      {rows.some((row) => row.capOff) && (
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          cap off: the single-stock cap could not be applied (a 15% cap needs at least 7
          constituents), so those sectors are shown with uncapped weights.
        </p>
      )}
    </div>
  );
}

