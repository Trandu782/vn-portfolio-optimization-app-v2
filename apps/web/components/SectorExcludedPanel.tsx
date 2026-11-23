"use client";

/**
 * Always-visible default-excluded tickers panel (docs/V2_SPEC.md section 3.2).
 *
 * Lists the tickers the adjustment checks drop for the current window (return-corrupting
 * anomalies that fall inside it), one plain-language summary line per ticker with the
 * main reason, the category (data glitch vs thin trading) and how many dates were
 * affected. The full list is behind a "details" disclosure. Tickers whose anomalies are
 * all outside the window are not dropped, and are listed separately as "flagged earlier,
 * not affecting this window". When the stored flags were computed under an older policy
 * the list is shown under the stale caveat and is not presented as authoritative.
 */

import type { SectorDefaultExcluded } from "@/lib/api";
import { summarizeExcluded, toExcludedView } from "@/lib/sector-analysis";

function ExcludedGroup({
  sector,
  tickers,
}: {
  sector: string;
  tickers: SectorDefaultExcluded[];
}) {
  return (
    <div className="rounded-md bg-gray-50 p-2 text-xs dark:bg-gray-900">
      <p className="font-medium">{sector}</p>
      <ul className="mt-1 space-y-1.5">
        {tickers.map((item) => {
          const view = toExcludedView(item);
          return (
            <li key={view.ticker}>
              <p>
                <span className="font-medium">{view.ticker}</span>{" "}
                <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px] dark:bg-gray-700">
                  {view.categoryLabel}
                </span>{" "}
                {view.summary}
              </p>
              {view.details.length > 0 && (
                <details className="ml-4 text-gray-500 dark:text-gray-400">
                  <summary className="cursor-pointer">details</summary>
                  <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
                    {view.details.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function SectorExcludedPanel({
  items,
  outsideWindow,
  includeDefaultExcluded,
  onToggle,
  flagsAvailable,
  flagsPolicyCurrent,
}: {
  items: SectorDefaultExcluded[];
  outsideWindow: SectorDefaultExcluded[];
  includeDefaultExcluded: boolean;
  onToggle: (value: boolean) => void;
  flagsAvailable: boolean;
  flagsPolicyCurrent: boolean;
}) {
  const groups = summarizeExcluded(items);
  const outsideGroups = summarizeExcluded(outsideWindow ?? []);
  const stale = flagsAvailable && !flagsPolicyCurrent;

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <h2 className="text-lg font-semibold">Tickers excluded by default</h2>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
        A sector index drops a ticker only when a bad price move falls inside the analysis
        window, so one bad series cannot distort a whole sector. These names are listed,
        never hidden.
      </p>

      {stale && (
        <p className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          Adjustment checks are outdated; rerun the update to refresh them. The excluded list
          below may be stale, so do not treat it as authoritative.
        </p>
      )}
      {!flagsAvailable && (
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          Adjustment-quality flags have not been computed yet; the precompute job populates
          them.
        </p>
      )}

      <label className="mt-2 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
        <input type="checkbox" checked={includeDefaultExcluded} onChange={(event) => onToggle(event.target.checked)} />
        Include these tickers in the indices anyway
      </label>

      {groups.length === 0 ? (
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          No tickers are excluded by the default checks in this window.
        </p>
      ) : (
        <div className="mt-2 space-y-2">
          {includeDefaultExcluded && (
            <p className="text-xs text-gray-500 dark:text-gray-400">These tickers are now included.</p>
          )}
          {groups.map((group) => (
            <ExcludedGroup key={group.sector} sector={group.sector} tickers={group.tickers} />
          ))}
        </div>
      )}

      {outsideGroups.length > 0 && (
        <details className="mt-3 rounded-md bg-gray-50 p-2 text-xs dark:bg-gray-900">
          <summary className="cursor-pointer font-medium">
            Flagged earlier, not affecting this window
          </summary>
          <p className="mt-1 text-gray-500 dark:text-gray-400">
            These tickers have a bad price move somewhere in their history, but none falls
            inside this window, so they are included in the indices.
          </p>
          <div className="mt-2 space-y-2">
            {outsideGroups.map((group) => (
              <ExcludedGroup key={group.sector} sector={group.sector} tickers={group.tickers} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
