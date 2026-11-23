import assert from "node:assert/strict";
import { test } from "node:test";

import {
  APP_STORAGE_KEY,
  APP_STORAGE_SCHEMA_VERSION,
  emptyAppState,
  loadAppState,
  saveAppState,
  type KeyValueStorage,
} from "./app-store.ts";
import type { UniverseBuildResponse } from "./api";

/** Minimal in-memory stand-in for `window.localStorage`. */
class MemoryStorage implements KeyValueStorage {
  private readonly items = new Map<string, string>();

  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.items.set(key, value);
  }
}

function buildResult(symbols: string[]): UniverseBuildResponse {
  return {
    start: "2022-01-01",
    end: "2024-01-01",
    symbols,
    adv_by_symbol: {},
    quality_flags: {},
    dropped: [],
    filters_applied: [],
    price_matrix: { dates: [], columns: symbols, data: [] },
    returns_matrix: { dates: [], columns: symbols, data: [] },
  } as unknown as UniverseBuildResponse;
}

test("universe and portfolio survive a save/load cycle", () => {
  const storage = new MemoryStorage();
  const state = emptyAppState();
  state.universe = {
    symbols: ["VNM", "FPT"],
    selected: ["VNM", "FPT"],
    start: "2022-01-01",
    end: "2024-01-01",
    filters: [{ id: "liquidity", params: { min_adv: 1_000_000 } }],
    result: buildResult(["VNM", "FPT"]),
  };
  state.portfolio = { holdings: [{ symbol: "VNM", shares: 100, avg_cost: 50_000 }], cash: 1_000 };

  saveAppState(storage, state);
  const loaded = loadAppState(storage);

  assert.deepEqual(loaded.universe?.symbols, ["VNM", "FPT"]);
  assert.deepEqual(loaded.universe?.selected, ["VNM", "FPT"]);
  assert.equal(loaded.universe?.start, "2022-01-01");
  assert.deepEqual(loaded.universe?.filters, [{ id: "liquidity", params: { min_adv: 1_000_000 } }]);
  assert.deepEqual(loaded.portfolio.holdings, [
    { symbol: "VNM", shares: 100, avg_cost: 50_000 },
  ]);
  assert.equal(loaded.portfolio.cash, 1_000);
});

test("loading a saved portfolio fills an empty working portfolio", () => {
  const storage = new MemoryStorage();
  const state = emptyAppState();
  state.library = {
    active_id: "p1",
    portfolios: [
      {
        id: "p1",
        name: "Test",
        portfolio: {
          holdings: [
            { symbol: "VNM", shares: 100, avg_cost: 50_000 },
            { symbol: "FPT", shares: 20, avg_cost: 90_000 },
          ],
          cash: 500_000,
        },
        updated_at: "2024-01-01T00:00:00Z",
      },
    ],
  };

  saveAppState(storage, state);
  const loaded = loadAppState(storage);

  assert.equal(loaded.portfolio.holdings.length, 2);
  assert.equal(loaded.portfolio.cash, 500_000);
});

test("edits to a loaded snapshot are not overwritten by the snapshot", () => {
  const storage = new MemoryStorage();
  const state = emptyAppState();
  state.library = {
    active_id: "p1",
    portfolios: [
      {
        id: "p1",
        name: "Test",
        portfolio: { holdings: [{ symbol: "VNM", shares: 100, avg_cost: 50_000 }], cash: 0 },
        updated_at: "2024-01-01T00:00:00Z",
      },
    ],
  };
  state.portfolio = { holdings: [{ symbol: "FPT", shares: 5, avg_cost: null }], cash: 10 };

  saveAppState(storage, state);
  const loaded = loadAppState(storage);

  assert.deepEqual(loaded.portfolio.holdings, [{ symbol: "FPT", shares: 5, avg_cost: null }]);
});

test("an incompatible stored universe is discarded instead of crashing", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    APP_STORAGE_KEY,
    JSON.stringify({
      version: APP_STORAGE_SCHEMA_VERSION,
      universe: { symbols: "not-an-array", result: { nope: true } },
    }),
  );

  const loaded = loadAppState(storage);
  assert.equal(loaded.universe, null);
});

test("a different schema version is discarded and starts fresh", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    APP_STORAGE_KEY,
    JSON.stringify({ version: APP_STORAGE_SCHEMA_VERSION + 1, universe: { symbols: ["VNM"] } }),
  );

  const loaded = loadAppState(storage);
  assert.equal(loaded.universe, null);
  assert.deepEqual(loaded.portfolio, { holdings: [], cash: 0 });
});

test("timeframes default and survive a save/load cycle", () => {
  const storage = new MemoryStorage();
  const state = emptyAppState();
  assert.equal(state.timeframes.optimize.preset, "3Y");
  assert.equal(state.timeframes.risk.preset, "1Y");

  state.timeframes.risk = { preset: "Custom", start: "2024-01-02", end: "2024-12-31" };
  saveAppState(storage, state);
  const loaded = loadAppState(storage);

  assert.equal(loaded.timeframes.optimize.preset, "3Y");
  assert.deepEqual(loaded.timeframes.risk, {
    preset: "Custom",
    start: "2024-01-02",
    end: "2024-12-31",
  });
});

test("a version-1 payload is migrated with default timeframes", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    APP_STORAGE_KEY,
    JSON.stringify({
      version: 1,
      universe: {
        symbols: ["VNM"],
        start: "2022-01-01",
        end: "2024-01-01",
        filters: [],
        result: buildResult(["VNM"]),
      },
    }),
  );

  const loaded = loadAppState(storage);
  assert.deepEqual(loaded.universe?.symbols, ["VNM"]);
  assert.equal(loaded.timeframes.optimize.preset, "3Y");
  assert.equal(loaded.timeframes.risk.preset, "1Y");
});

test("sector weighting, cap and timeframe default and survive a save/load cycle", () => {
  const storage = new MemoryStorage();
  const state = emptyAppState();
  assert.equal(state.v2Filter.weighting, "market_cap");
  assert.equal(state.v2Filter.capPercent, 15);
  assert.equal(state.v2Filter.includeDefaultExcluded, false);
  assert.equal(state.timeframes.sector.preset, "1Y");

  state.v2Filter = {
    ...state.v2Filter,
    benchmark: "VN30",
    weighting: "equal",
    capPercent: null,
    includeDefaultExcluded: true,
  };
  state.timeframes.sector = { preset: "Custom", start: "2024-01-02", end: "2024-12-31" };
  saveAppState(storage, state);
  const loaded = loadAppState(storage);

  assert.equal(loaded.v2Filter.benchmark, "VN30");
  assert.equal(loaded.v2Filter.weighting, "equal");
  assert.equal(loaded.v2Filter.capPercent, null);
  assert.equal(loaded.v2Filter.includeDefaultExcluded, true);
  assert.deepEqual(loaded.timeframes.sector, {
    preset: "Custom",
    start: "2024-01-02",
    end: "2024-12-31",
  });
});

test("a version-3 payload migrates the weighting controls and keeps the sector timeframe", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    APP_STORAGE_KEY,
    JSON.stringify({
      version: 3,
      v2Filter: {
        preset: "high_liquidity",
        benchmark: "VN100",
        sectors: [],
        indexes: [],
        exchange: null,
        excludeAdjustmentFlagged: true,
      },
      timeframes: {
        optimize: { preset: "3Y", start: "", end: "" },
        risk: { preset: "1Y", start: "", end: "" },
        sector: { preset: "6M", start: "", end: "" },
      },
    }),
  );
  const loaded = loadAppState(storage);
  assert.equal(loaded.v2Filter.preset, "high_liquidity");
  assert.equal(loaded.v2Filter.benchmark, "VN100");
  assert.equal(loaded.v2Filter.weighting, "market_cap");
  assert.equal(loaded.v2Filter.capPercent, 15);
  assert.equal(loaded.v2Filter.includeDefaultExcluded, false);
  assert.equal(loaded.timeframes.sector.preset, "6M");
});

test("an unknown stored liquidity preset migrates to Standard Retail", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    APP_STORAGE_KEY,
    JSON.stringify({
      version: APP_STORAGE_SCHEMA_VERSION,
      v2Filter: { preset: "bogus_preset", includeDefaultExcluded: true },
    }),
  );

  const loaded = loadAppState(storage);
  // The corrupt preset falls back to the default; a stored true is the user's choice.
  assert.equal(loaded.v2Filter.preset, "standard_retail");
  assert.equal(loaded.v2Filter.includeDefaultExcluded, true);
});

test("the default shared filter is Standard Retail with default-excluded opt-in off", () => {
  const state = emptyAppState();
  assert.equal(state.v2Filter.preset, "standard_retail");
  assert.equal(state.v2Filter.includeDefaultExcluded, false);
});

