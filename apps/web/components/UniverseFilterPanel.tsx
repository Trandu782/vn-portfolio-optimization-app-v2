"use client";

/**
 * The shared V2 universe filter for the Optimize tab.
 *
 * It renders the sector multi-select (ICB level 2), the VN30/VN100 chips, the
 * liquidity preset and the live "N tickers pass" counter, and it calls the read-only
 * `/v2/universe` and `/v2/sectors` endpoints. The selection lives in the single app
 * store (`v2Filter`), so it survives tab switches and reloads. Filtering is done by
 * the API (`filter_universe`); this component never re-implements it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
      return function () {
        active = false;
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
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="block font-medium">Liquidity preset</span>
          <select
            value={v2Filter.preset}
            onChange={(event) => setV2Filter({ ...v2Filter, preset: event.target.value })}
            className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          >
            {PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
            Market cap is full (free-float is unavailable); ADTV and ADV are the real
            liquidity guards.
          </span>
        </label>
        <div className="block text-sm">
          <span className="block font-medium">Index membership</span>
          <div className="mt-1 flex flex-wrap gap-2">
            {["VN30", "VN100"].map((code) => {
              const active = v2Filter.indexes.includes(code);
              return (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggleIndex(code)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium ${
                    active
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-gray-300 text-gray-700 dark:border-gray-700 dark:text-gray-200"
                  }`}
                >
                  {code}
                </button>
              );
            })}
          </div>
          <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
            Chips are ANDed with the sector selection. VN30 is a subset of VN100.
          </span>
        </div>
      </div>

      {unavailable ? (
        <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          V2 data not available: the precompute job has not populated the database. You can
          still pick tickers manually below.
        </p>
      ) : (
        <div>
          <span className="block text-sm font-medium">Sectors (ICB level 2)</span>
          {sectors && !sectors.available && (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
              Sector list unavailable; type tickers manually below.
            </p>
          )}
          <div className="mt-1 flex max-h-40 flex-wrap gap-1 overflow-auto rounded-md border border-gray-200 p-2 dark:border-gray-800">
            {sectorOptions.length === 0 && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Loading sectors\u2026
              </span>
            )}
            {sectorOptions.map((sector) => {
              const active = v2Filter.sectors.includes(sector.name);
              return (
                <button
                  key={sector.name}
                  type="button"
                  onClick={() => toggleSector(sector.name)}
                  className={`rounded-full border px-2 py-0.5 text-xs ${
                    active
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-gray-300 text-gray-700 dark:border-gray-700 dark:text-gray-200"
                  }`}
                >
                  {sector.name} ({sector.passing}/{sector.total})
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-md bg-gray-100 px-3 py-1 text-sm font-medium dark:bg-gray-800">
          {loading ? "Counting\u2026" : `${passingCount} tickers pass`}
        </span>
        <button
          type="button"
          onClick={addAllPassing}
          disabled={loading || unavailable || passingCount === 0}
          className="rounded-md border border-blue-600 px-3 py-1 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50 dark:text-blue-400 dark:hover:bg-blue-950"
        >
          Add all passing (max {maxStocks})
        </button>
        <label className="flex items-center gap-1 text-xs text-gray-600 dark:text-gray-300">
          <input
            type="checkbox"
            checked={v2Filter.excludeAdjustmentFlagged}
            onChange={(event) =>
              setV2Filter({ ...v2Filter, excludeAdjustmentFlagged: event.target.checked })
            }
          />
          Exclude tickers flagged for adjustment quality
        </label>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {trimMessage && (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          {trimMessage}
        </p>
      )}

      {universe && (
        <div className="space-y-1">
          {(universe.warnings ?? []).map((warning) => (
            <p
              key={warning}
              className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200"
            >
              {warning}
            </p>
          ))}
          {universe.flags_available === false && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Adjustment-quality flags have not been computed yet (the precompute job
              populates them).
            </p>
          )}
          {universe.flags_available === true && universe.flags_policy_current === false && (
            <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
              Adjustment checks are outdated; rerun the update to refresh them.
            </p>
          )}
          {(universe.adjustment_flags ?? []).length > 0 && (
            <details className="rounded-md bg-gray-50 p-2 text-xs dark:bg-gray-900">
              <summary className="cursor-pointer font-medium">
                {(universe.adjustment_flags ?? []).length} adjustment-quality flag(s)
              </summary>
              <ul className="mt-1 space-y-0.5">
                {(universe.adjustment_flags ?? []).map((flag) => (
                  <li key={flag.ticker}>
                    <span className="font-medium">{flag.ticker}</span>:{" "}
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
