"use client";

import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
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
    <div className="rounded-lg border border-hairline bg-raised/50 p-3 text-xs">
      <p className="font-medium text-fg">{sector}</p>
      <ul className="mt-2 space-y-2">
        {tickers.map((item) => {
          const view = toExcludedView(item);
          return (
            <li key={view.ticker} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-fg-secondary">
                <span className="font-mono font-medium text-fg">{view.ticker}</span>
                <Badge tone="neutral">{view.categoryLabel}</Badge>
                <span>{view.summary}</span>
              </div>
              {view.details.length > 0 && (
                <details className="ml-4 text-fg-muted">
                  <summary className="cursor-pointer hover:text-fg">details</summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
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
    <Card className="space-y-3">
      <div>
        <h2 className="text-base font-medium text-fg">Tickers excluded by default</h2>
        <p className="mt-1 text-xs text-fg-muted">
          A sector index drops a ticker only when a bad price move falls inside the analysis
          window, so one bad series cannot distort a whole sector. These names are listed,
          never hidden.
        </p>
      </div>

      {stale && (
        <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          Adjustment checks are outdated; rerun the update to refresh them. The excluded list
          below may be stale, so do not treat it as authoritative.
        </p>
      )}
      {!flagsAvailable && (
        <p className="text-xs text-fg-muted">
          Adjustment-quality flags have not been computed yet; the precompute job populates
          them.
        </p>
      )}

      <label className="flex min-h-[36px] cursor-pointer items-center gap-2 text-xs text-fg-secondary">
        <input
          type="checkbox"
          checked={includeDefaultExcluded}
          onChange={(event) => onToggle(event.target.checked)}
          className="h-4 w-4 accent-accent"
        />
        <span>Include these tickers in the indices anyway</span>
      </label>

      {groups.length === 0 ? (
        <p className="text-xs text-fg-muted">
          No tickers are excluded by the default checks in this window.
        </p>
      ) : (
        <div className="space-y-2">
          {includeDefaultExcluded && (
            <p className="text-xs text-fg-muted">These tickers are now included.</p>
          )}
          {groups.map((group) => (
            <ExcludedGroup key={group.sector} sector={group.sector} tickers={group.tickers} />
          ))}
        </div>
      )}

      {outsideGroups.length > 0 && (
        <details className="rounded-lg border border-hairline bg-raised/40 p-3 text-xs">
          <summary className="cursor-pointer font-medium text-fg-secondary">
            Flagged earlier, not affecting this window
          </summary>
          <p className="mt-1.5 text-fg-muted">
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
    </Card>
  );
}
