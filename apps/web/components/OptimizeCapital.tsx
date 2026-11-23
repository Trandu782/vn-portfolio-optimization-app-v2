"use client";

/**
 * Money source selector for the Optimize page.
 *
 * "Use my holdings (including cash)" takes the capital from the shared portfolio
 * (value at the latest prices, including cash) so the user never re-enters it.
 * "New money" lets the user type a fresh amount. It is a controlled component:
 * the Optimize builder owns the mode and typed amount and reads the resolved
 * capital through `resolveCapital`.
 */

import Link from "next/link";

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
      <div className="space-y-2 text-sm">
        <label className="flex items-start gap-2">
          <input
            type="radio"
            name="capital-mode"
            checked={mode === "holdings"}
            onChange={() => onModeChange("holdings")}
            className="mt-1"
          />
          <span>
            <span className="font-medium">Use my holdings (including cash)</span>
            <span className="mt-0.5 block text-xs text-gray-500 dark:text-gray-400">
              Capital = portfolio value including cash:{" "}
              {portfolioValue === null
                ? loading
                  ? "calculating\u2026"
                  : "\u2014"
                : formatVnd(portfolioValue)}
            </span>
          </span>
        </label>

        <label className="flex items-start gap-2">
          <input
            type="radio"
            name="capital-mode"
            checked={mode === "new"}
            onChange={() => onModeChange("new")}
            className="mt-1"
          />
          <span>
            <span className="font-medium">New money</span>
            <span className="mt-0.5 block text-xs text-gray-500 dark:text-gray-400">
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
            className="ml-6 w-56 rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
          />
        )}
      </div>

      <div className="rounded-md bg-gray-50 p-3 text-sm dark:bg-gray-900">
        <span className="font-medium">Money to invest: {formatVnd(resolvedCapital)}</span>
        {mode === "holdings" && holdings.length === 0 && (
          <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
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