"use client";

import Link from "next/link";

import { inputClass } from "@/components/ui/Field";
import { formatVnd } from "@/lib/format";
import { usePortfolio } from "@/lib/portfolio-context";

export type CapitalMode = "holdings" | "new";

export interface OptimizeCapitalProps {
  mode: CapitalMode;
  newCapital: string;
  onModeChange: (mode: CapitalMode) => void;
  onNewCapitalChange: (value: string) => void;
}

/** Resolve the capital (VND) from the portfolio value or the typed amount. */
export function resolveCapital(
  mode: CapitalMode,
  portfolioValue: number | null,
  newCapital: string,
): number {
  if (mode === "holdings") {
    return portfolioValue ?? 0;
  }
  return Math.max(0, Math.trunc(Number(newCapital) || 0));
}

export function OptimizeCapital({
  mode,
  newCapital,
  onModeChange,
  onNewCapitalChange,
}: OptimizeCapitalProps) {
  const { holdings, evaluation, loading } = usePortfolio();
  const portfolioValue = evaluation?.total_value ?? null;
  const resolvedCapital = resolveCapital(mode, portfolioValue, newCapital);

  return (
    <div className="space-y-3">
      <div className="space-y-2.5 text-sm">
        <label className="flex cursor-pointer items-start gap-2.5">
          <input
            type="radio"
            name="capital-mode"
            checked={mode === "holdings"}
            onChange={() => onModeChange("holdings")}
            className="mt-1 h-4 w-4 accent-accent"
          />
          <span>
            <span className="font-medium text-fg">Use my holdings (including cash)</span>
            <span className="mt-0.5 block text-xs text-fg-muted">
              Capital = portfolio value including cash:{" "}
              <span className="font-mono tabular-nums text-fg-secondary">
                {portfolioValue === null
                  ? loading
                    ? "calculating\u2026"
                    : "\u2014"
                  : formatVnd(portfolioValue)}
              </span>
            </span>
          </span>
        </label>

        <label className="flex cursor-pointer items-start gap-2.5">
          <input
            type="radio"
            name="capital-mode"
            checked={mode === "new"}
            onChange={() => onModeChange("new")}
            className="mt-1 h-4 w-4 accent-accent"
          />
          <span>
            <span className="font-medium text-fg">New money</span>
            <span className="mt-0.5 block text-xs text-fg-muted">
              Type the amount to invest in VND.
            </span>
          </span>
        </label>

        {mode === "new" && (
          <input
            type="number"
            inputMode="numeric"
            min={0}
            step={1_000_000}
            value={newCapital}
            onChange={(event) => onNewCapitalChange(event.target.value)}
            placeholder="e.g. 500000000"
            className={`${inputClass} ml-6 w-56 font-mono tabular-nums`}
          />
        )}
      </div>

      <div className="rounded-lg border border-hairline bg-raised/60 px-3 py-2.5 text-sm">
        <span className="text-fg-secondary">Money to invest: </span>
        <span className="font-mono font-medium tabular-nums text-fg">
          {formatVnd(resolvedCapital)}
        </span>
        {mode === "holdings" && holdings.length === 0 && (
          <span className="ml-2 text-xs text-warn">
            Add holdings on the{" "}
            <Link href="/portfolio" className="underline">
              Portfolio
            </Link>{" "}
            page first.
          </span>
        )}
      </div>
    </div>
  );
}
