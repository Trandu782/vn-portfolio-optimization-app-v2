"use client";

import { InfoTip } from "@/components/InfoTip";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import {
  tableBodyCellClass,
  tableHeaderCellClass,
  tableHeaderRowClass,
  tableRowHoverClass,
} from "@/components/ui/Field";
import { ChevronDownIcon, ChevronUpIcon } from "@/components/ui/Icons";
import { formatPercent, formatSignedPercent } from "@/lib/chart-theme";
import {
  isRowGreyed,
  rowBadge,
  type SectorRow,
  type SectorSortKey,
  type SortDirection,
} from "@/lib/sector-analysis";

const COLUMNS: Array<{
  key: SectorSortKey;
  label: string;
  tip: string;
  numeric?: boolean;
}> = [
  { key: "name", label: "Sector", tip: "ICB level-2 sector name." },
  {
    key: "period_return",
    label: "Period",
    tip: "Return of the sector index over the window.",
    numeric: true,
  },
  {
    key: "excess_return",
    label: "Excess",
    tip: "Sector return minus the benchmark's over the window.",
    numeric: true,
  },
  {
    key: "beta",
    label: "Beta",
    tip: "Sensitivity to the benchmark; 1 means it moves with it.",
    numeric: true,
  },
  {
    key: "r_squared",
    label: "R\u00b2",
    tip: "How much of the sector's move the benchmark explains (0-1).",
    numeric: true,
  },
  {
    key: "annualized_volatility",
    label: "Volatility",
    tip: "Annualised standard deviation of daily returns.",
    numeric: true,
  },
  {
    key: "constituent_count",
    label: "Constituents",
    tip: "Stocks in the sector index; default-excluded names are not counted.",
    numeric: true,
  },
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
    <Card className="space-y-3">
      <div>
        <h2 className="text-base font-medium text-fg">Sector beta &amp; performance</h2>
        <p className="mt-1 text-xs text-fg-muted">
          How each sector moved and how sensitive it is to the benchmark. Beta above 1 means it
          swings more than the market; excess return is the period return minus the benchmark&apos;s.
          Tick the sectors to send to the Optimizer.
        </p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-hairline">
        <table className="min-w-full text-sm">
          <caption className="sr-only">
            Sortable sector performance and risk metrics with a send-to-Optimizer checkbox.
          </caption>
          <thead>
            <tr className={tableHeaderRowClass}>
              <th scope="col" className="px-3 py-2.5">
                <span className="sr-only">Send to Optimizer</span>
              </th>
              {COLUMNS.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={`${tableHeaderCellClass} ${column.numeric ? "text-right" : ""}`}
                >
                  <button
                    type="button"
                    onClick={() => onSort(column.key)}
                    className="inline-flex items-center gap-1 transition-colors duration-150 ease-unslop hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm"
                    aria-label={`Sort by ${column.label}`}
                  >
                    <span>{column.label}</span>
                    {sortKey === column.key ? (
                      sortDirection === "asc" ? (
                        <ChevronUpIcon size={13} />
                      ) : (
                        <ChevronDownIcon size={13} />
                      )
                    ) : null}
                  </button>
                  <InfoTip text={column.tip} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const greyed = isRowGreyed(row);
              const badge = rowBadge(row);
              return (
                <tr
                  key={row.name}
                  className={`${tableRowHoverClass} ${greyed ? "opacity-50" : ""}`}
                >
                  <td className="px-3 py-3">
                    <input
                      type="checkbox"
                      disabled={greyed}
                      checked={!greyed && selected.has(row.name)}
                      onChange={() => onToggle(row.name)}
                      aria-label={`Send ${row.name} to the Optimizer`}
                      className="h-4 w-4 accent-accent"
                    />
                  </td>
                  <th
                    scope="row"
                    className={`${tableBodyCellClass} text-left font-medium text-fg`}
                  >
                    <div className="flex items-center gap-2">
                      <span>{row.name}</span>
                      {badge && (
                        <Badge tone={badge.tone === "warning" ? "warn" : "neutral"}>
                          {badge.label}
                        </Badge>
                      )}
                      {row.capOff && (
                        <span
                          title={row.capOffReason ?? "The single-stock cap could not be applied."}
                          className="rounded-md border border-strong bg-raised px-2 py-0.5 font-mono text-xs text-fg-secondary"
                        >
                          cap off
                        </span>
                      )}
                    </div>
                  </th>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {percentCell(row.periodReturn, true)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {percentCell(row.excessReturn, true)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {numberCell(row.beta, 2)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {numberCell(row.rSquared, 2)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg-secondary`}
                  >
                    {percentCell(row.volatility, false)}
                  </td>
                  <td
                    className={`${tableBodyCellClass} text-right font-mono tabular-nums text-fg`}
                  >
                    {row.constituentCount}
                    {row.defaultExcludedCount > 0 && (
                      <span className="ml-1 text-xs text-fg-muted">
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

      <p className="text-xs text-fg-muted">
        A sector needs at least 3 constituents to publish an index; thinner sectors are greyed
        and cannot be sent. (-n) marks constituents dropped by the default adjustment checks.
      </p>
      {rows.some((row) => row.capOff) && (
        <p className="text-xs text-fg-muted">
          cap off: the single-stock cap could not be applied (a 15% cap needs at least 7
          constituents), so those sectors are shown with uncapped weights.
        </p>
      )}
    </Card>
  );
}
