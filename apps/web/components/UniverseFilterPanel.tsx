"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { selectClass } from "@/components/ui/Field";
import {
  fetchV2Sectors,
  fetchV2Universe,
  type AdjustmentQualityFlag,
  type V2SectorsResponse,
  type V2UniverseResponse,
} from "@/lib/api";
import { useAppStore } from "@/lib/app-store-context";

export interface V2UniverseView {
  available: boolean;
  sectorByTicker: Record<string, string>;
  warnings: string[];
  flags: AdjustmentQualityFlag[];
  flagsAvailable: boolean;
  flagsPolicyCurrent: boolean;
  /** Passing tickers sorted by ADTV (largest first). */
  passing: string[];
}

const EMPTY_VIEW: V2UniverseView = {
  available: false,
  sectorByTicker: {},
  warnings: [],
  flags: [],
  flagsAvailable: false,
  flagsPolicyCurrent: false,
  passing: [],
};

const PRESETS = [
  { id: "small_retail", label: "Small retail (< 1B VND)" },
  { id: "standard_retail", label: "Standard retail (1B\u201310B VND)" },
  { id: "high_liquidity", label: "High liquidity (\u2265 10B VND)" },
  { id: "all_stocks", label: "All stocks" },
];

interface UniverseFilterPanelProps {
  selected: string[];
  maxStocks: number;
  onAddMany: (symbols: string[]) => void;
  onUniverse: (view: V2UniverseView) => void;
}

export function UniverseFilterPanel({
  selected,
  maxStocks,
  onAddMany,
  onUniverse,
}: UniverseFilterPanelProps) {
  const { v2Filter, setV2Filter } = useAppStore();
  const [sectors, setSectors] = useState<V2SectorsResponse | null>(null);
  const [universe, setUniverse] = useState<V2UniverseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trimMessage, setTrimMessage] = useState<string | null>(null);

  const onUniverseRef = useRef(onUniverse);
  onUniverseRef.current = onUniverse;

  useEffect(
    function () {
      let active = true;
      fetchV2Sectors(v2Filter.preset)
        .then(function (payload) {
          if (active) setSectors(payload);
        })
        .catch(function () {
          if (active) setSectors(null);
        });
      return function () {
        active = false;
      };
    },
    [v2Filter.preset],
  );

  useEffect(
    function () {
      let active = true;
      setLoading(true);
      setError(null);
      const timer = setTimeout(function () {
        fetchV2Universe({
          preset: v2Filter.preset,
          sectors: v2Filter.sectors,
          indexes: v2Filter.indexes,
          exchange: v2Filter.exchange,
          exclude_adjustment_flagged: v2Filter.excludeAdjustmentFlagged,
        })
          .then(function (payload) {
            if (!active) return;
            setUniverse(payload);
            const sectorByTicker: Record<string, string> = {};
            for (const ticker of payload.kept ?? []) {
              if (ticker.sector) sectorByTicker[ticker.ticker] = ticker.sector;
            }
            const passing = [...(payload.kept ?? [])]
              .sort((a, b) => (b.adtv_median ?? 0) - (a.adtv_median ?? 0))
              .map((ticker) => ticker.ticker);
            onUniverseRef.current({
              available: payload.available,
              sectorByTicker,
              warnings: payload.warnings ?? [],
              flags: payload.adjustment_flags ?? [],
              flagsAvailable: payload.flags_available ?? false,
              flagsPolicyCurrent: payload.flags_policy_current ?? false,
              passing,
            });
          })
          .catch(function (err: unknown) {
            if (!active) return;
            setError(err instanceof Error ? err.message : "Failed to load the V2 universe.");
            onUniverseRef.current({ ...EMPTY_VIEW });
          })
          .finally(function () {
            if (active) setLoading(false);
          });
      }, 200);
      return function () {
        active = false;
        clearTimeout(timer);
      };
    },
    [v2Filter],
  );

  const passingCount = universe?.kept?.length ?? 0;

  const toggleSector = useCallback(
    function (name: string) {
      const has = v2Filter.sectors.includes(name);
      const next = has
        ? v2Filter.sectors.filter((item) => item !== name)
        : [...v2Filter.sectors, name];
      setV2Filter({ ...v2Filter, sectors: next });
    },
    [v2Filter, setV2Filter],
  );

  const toggleIndex = useCallback(
    function (code: string) {
      const has = v2Filter.indexes.includes(code);
      const next = has
        ? v2Filter.indexes.filter((item) => item !== code)
        : [...v2Filter.indexes, code];
      setV2Filter({ ...v2Filter, indexes: next });
    },
    [v2Filter, setV2Filter],
  );

  const addAllPassing = useCallback(
    function () {
      setTrimMessage(null);
      const passing = universe
        ? [...(universe.kept ?? [])].sort((a, b) => (b.adtv_median ?? 0) - (a.adtv_median ?? 0))
        : [];
      if (passing.length === 0) return;
      const room = Math.max(0, maxStocks - selected.length);
      if (room === 0) {
        setTrimMessage(
          `You already have ${selected.length} tickers (the maximum is ${maxStocks}).`,
        );
        return;
      }
      const toAdd = passing
        .map((ticker) => ticker.ticker)
        .filter((code) => !selected.includes(code))
        .slice(0, room);
      onAddMany(toAdd);
      if (passing.length > room) {
        setTrimMessage(
          `${passing.length} tickers pass; added the ${toAdd.length} most liquid (max ${maxStocks}).`,
        );
      }
    },
    [universe, maxStocks, selected, onAddMany],
  );

  const sectorOptions = useMemo(
    () => (sectors?.sectors ?? []).slice().sort((a, b) => b.total - a.total),
    [sectors],
  );

  const unavailable = universe !== null && !universe.available;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="v2-liquidity-preset" className="block text-sm font-medium text-fg">
            Liquidity preset
          </label>
          <select
            id="v2-liquidity-preset"
            value={v2Filter.preset}
            onChange={(event) => setV2Filter({ ...v2Filter, preset: event.target.value })}
            className={`${selectClass} w-full`}
          >
            {PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-fg-muted">
            Market cap is full (free-float is unavailable); ADTV and ADV are the real liquidity
            guards.
          </p>
        </div>

        <div className="space-y-1.5">
          <span className="block text-sm font-medium text-fg">Index membership</span>
          <div className="flex flex-wrap gap-2">
            {["VN30", "VN100"].map((code) => {
              const active = v2Filter.indexes.includes(code);
              return (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggleIndex(code)}
                  aria-pressed={active}
                  className={`min-h-[40px] md:min-h-[36px] rounded-md border px-3 py-1.5 font-mono text-xs font-medium transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                    active
                      ? "border-accent bg-accent text-white"
                      : "border-strong bg-raised text-fg-secondary hover:bg-surface hover:text-fg"
                  }`}
                >
                  {code}
                </button>
              );
            })}
          </div>
          <p className="text-xs text-fg-muted">
            Chips are ANDed with the sector selection. VN30 is a subset of VN100.
          </p>
        </div>
      </div>

      {unavailable ? (
        <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          V2 data not available: the precompute job has not populated the database. You can
          still pick tickers manually below.
        </p>
      ) : (
        <div className="space-y-1.5">
          <span className="block text-sm font-medium text-fg">Sectors (ICB level 2)</span>
          {sectors && !sectors.available && (
            <p className="text-xs text-warn">
              Sector list unavailable; type tickers manually below.
            </p>
          )}
          <div className="flex max-h-44 flex-wrap gap-1.5 overflow-auto rounded-lg border border-hairline bg-raised/40 p-2.5">
            {sectorOptions.length === 0 && (
              <span className="text-xs text-fg-muted">Loading sectors&hellip;</span>
            )}
            {sectorOptions.map((sector) => {
              const active = v2Filter.sectors.includes(sector.name);
              return (
                <button
                  key={sector.name}
                  type="button"
                  onClick={() => toggleSector(sector.name)}
                  aria-pressed={active}
                  className={`rounded-md border px-2.5 py-1 text-xs transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                    active
                      ? "border-accent bg-accent text-white"
                      : "border-hairline bg-surface text-fg-secondary hover:border-strong hover:text-fg"
                  }`}
                >
                  {sector.name}{" "}
                  <span className="font-mono tabular-nums opacity-80">
                    ({sector.passing}/{sector.total})
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-md border border-hairline bg-raised px-3 py-1.5 font-mono text-xs font-medium tabular-nums text-fg">
          {loading ? "Counting\u2026" : `${passingCount} tickers pass`}
        </span>
        <Button
          size="sm"
          onClick={addAllPassing}
          disabled={loading || unavailable || passingCount === 0}
        >
          Add all passing (max {maxStocks})
        </Button>
        <label className="flex min-h-[36px] cursor-pointer items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={v2Filter.excludeAdjustmentFlagged}
            onChange={(event) =>
              setV2Filter({ ...v2Filter, excludeAdjustmentFlagged: event.target.checked })
            }
            className="h-4 w-4 rounded border-strong accent-accent"
          />
          <span>Exclude tickers flagged for adjustment quality</span>
        </label>
      </div>

      {error && <p className="text-sm text-negative">{error}</p>}
      {trimMessage && (
        <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
          {trimMessage}
        </p>
      )}

      {universe && (
        <div className="space-y-2">
          {(universe.warnings ?? []).map((warning) => (
            <p
              key={warning}
              className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn"
            >
              {warning}
            </p>
          ))}
          {universe.flags_available === false && (
            <p className="text-xs text-fg-muted">
              Adjustment-quality flags have not been computed yet (the precompute job
              populates them).
            </p>
          )}
          {universe.flags_available === true && universe.flags_policy_current === false && (
            <p className="rounded-lg border border-warn-border bg-warn-subtle px-3 py-2 text-xs text-warn">
              Adjustment checks are outdated; rerun the update to refresh them.
            </p>
          )}
          {(universe.adjustment_flags ?? []).length > 0 && (
            <details className="rounded-lg border border-hairline bg-raised/50 p-3 text-xs">
              <summary className="cursor-pointer font-medium text-fg-secondary">
                {(universe.adjustment_flags ?? []).length} adjustment-quality flag(s)
              </summary>
              <ul className="mt-2 space-y-1 text-fg-secondary">
                {(universe.adjustment_flags ?? []).map((flag) => (
                  <li key={flag.ticker}>
                    <span className="font-mono font-medium text-fg">{flag.ticker}</span>:{" "}
                    {(flag.reasons ?? []).join("; ")}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
