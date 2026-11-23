/**
 * The single persisted client store.
 *
 * Every page reads its shared inputs from here (active portfolio, universe
 * selection, optimization result, chosen portfolio and user settings) so
 * navigating away and back, or reloading the tab, never loses work. The shape
 * lives in one localStorage key with an explicit schema version; an incompatible
 * payload is discarded instead of crashing the page. This module is pure and has
 * no React import, so the persistence logic is unit-tested with a fake storage.
 */

import type {
  OptimizeResult,
  UniverseBuildResponse,
  UniverseFilterSelection,
} from "./api";
import {
  EMPTY_PORTFOLIO,
  sanitizeNamedPortfolios,
  sanitizePortfolio,
  type Portfolio,
  type PortfolioLibrary,
} from "./portfolio.ts";
import {
  DEFAULT_SECTOR_TIMEFRAME,
  sanitizeSectorTimeframe,
  type SectorTimeframeSelection,
} from "./sector-timeframe.ts";
import {
  DEFAULT_OPTIMIZE_TIMEFRAME,
  DEFAULT_RISK_TIMEFRAME,
  sanitizeTimeframe,
  type TimeframeSelection,
} from "./timeframe.ts";
import type { UserSettings } from "./user-settings.ts";

/** A built universe: the kept tickers, the window, the filters and the result. */
export interface UniverseSelection {
  /** Kept ticker codes. */
  symbols: string[];
  /** The raw tickers the user chose (before filters), so edits survive a reload. */
  selected: string[];
  /** Inclusive ISO start date. */
  start: string;
  /** Inclusive ISO end date. */
  end: string;
  /** Filters that were applied when the universe was built. */
  filters: UniverseFilterSelection[];
  /** The full build result (matrices, ADV, quality flags, dropped tickers). */
  result: UniverseBuildResponse;
}

/** The portfolio the user chose to carry forward (the "optimized" one). */
export interface ChosenPortfolio {
  weights: Record<string, number>;
  source: "optimized";
}

/** The per-tab analysis windows; each page keeps its own but all persist. */
export interface Timeframes {
  optimize: TimeframeSelection;
  risk: TimeframeSelection;
  sector: SectorTimeframeSelection;
}

/**
 * The shared V2 universe-filter selection. The Optimize tab writes it; every tab
 * reads it, so the sector/index/preset choices survive tab switches and reloads.
 */
export interface UniverseFilterState {
  /** Liquidity preset id (small_retail, standard_retail, high_liquidity, all_stocks). */
  preset: string;
  /** Selected ICB level-2 sector names. */
  sectors: string[];
  /** Selected index chips ("VN30" / "VN100"). */
  indexes: string[];
  /** Optional single exchange facet (HOSE/HNX/UPCOM), or null. */
  exchange: string | null;
  /** Benchmark code for the Sector tab ("VNINDEX" / "VN30" / "VN100"). */
  benchmark: string;
  /** Opt-in to drop tickers with adjustment-quality flags (default false). */
  excludeAdjustmentFlagged: boolean;
  /** Sector-index weighting: full market cap (default) or equal weight. */
  weighting: "market_cap" | "equal";
  /** Single-stock cap as a percent in (0, 100], or null for no cap. */
  capPercent: number | null;
  /** Opt-in to include the default-excluded (return-corrupting) tickers. */
  includeDefaultExcluded: boolean;
}

/** The default shared filter (Standard Retail, all sectors, VN-Index benchmark). */
export const DEFAULT_V2_FILTER: UniverseFilterState = {
  preset: "standard_retail",
  sectors: [],
  indexes: [],
  exchange: null,
  benchmark: "VNINDEX",
  excludeAdjustmentFlagged: false,
  weighting: "market_cap",
  capPercent: 15,
  includeDefaultExcluded: false,
};

/** Known liquidity preset ids (must match the data layer's `LIQUIDITY_PRESETS`). */
export const LIQUIDITY_PRESET_IDS = [
  "small_retail",
  "standard_retail",
  "high_liquidity",
  "all_stocks",
] as const;

export type LiquidityPresetId = (typeof LIQUIDITY_PRESET_IDS)[number];

/** True when `value` is one of the known liquidity preset ids. */
export function isLiquidityPresetId(value: unknown): value is LiquidityPresetId {
  return (
    typeof value === "string" &&
    (LIQUIDITY_PRESET_IDS as readonly string[]).includes(value)
  );
}

/** Everything the app shares between pages and persists across reloads. */
export interface AppState {
  portfolio: Portfolio;
  library: PortfolioLibrary;
  universe: UniverseSelection | null;
  v2Filter: UniverseFilterState;
  optimize: OptimizeResult | null;
  chosenPortfolio: ChosenPortfolio | null;
  settings: UserSettings | null;
  timeframes: Timeframes;
}

/** Minimal `Storage` surface so the persistence functions stay testable. */
export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** Version of the persisted payload. Bump when the stored shape changes. */
export const APP_STORAGE_SCHEMA_VERSION = 4;

/**
 * Versions this build can still read. Version 1 predates the per-tab timeframes;
 * version 2 predates the shared V2 universe filter and the sector timeframe; version
 * 3 predates the Sector weighting/cap controls. All are migrated by filling the
 * defaults rather than discarded, so an existing browser keeps its data.
 */
const SUPPORTED_SCHEMA_VERSIONS = new Set<number>([1, 2, 3, APP_STORAGE_SCHEMA_VERSION]);

/** The one localStorage key that holds the whole shared store. */
export const APP_STORAGE_KEY = "vnopt.app";

// Legacy per-feature keys, read once so an existing browser keeps its data.
const LEGACY_PORTFOLIO_KEY = "vnopt.portfolio";
const LEGACY_LIBRARY_KEY = "vnopt.portfolios";
const LEGACY_SETTINGS_KEY = "vnopt.user-settings";

/** Return a fresh empty store (never share mutable defaults between callers). */
export function emptyAppState(): AppState {
  return {
    portfolio: { holdings: [], cash: 0 },
    library: { portfolios: [], active_id: null },
    universe: null,
    v2Filter: { ...DEFAULT_V2_FILTER, sectors: [], indexes: [] },
    optimize: null,
    chosenPortfolio: null,
    settings: null,
    timeframes: {
      optimize: { ...DEFAULT_OPTIMIZE_TIMEFRAME },
      risk: { ...DEFAULT_RISK_TIMEFRAME },
      sector: { ...DEFAULT_SECTOR_TIMEFRAME },
    },
  };
}

/** The browser's storage, or `null` during server rendering. */
export function browserStorage(): KeyValueStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function parseJson(raw: string | null): unknown {
  if (raw === null) {
    return null;
  }
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function read(storage: KeyValueStorage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function sanitizeFilters(value: unknown): UniverseFilterSelection[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const filters: UniverseFilterSelection[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.id !== "string") {
      continue;
    }
    filters.push({ id: item.id, params: isRecord(item.params) ? { ...item.params } : {} });
  }
  return filters;
}

/**
 * Coerce a stored universe into the current shape, returning `null` when it is
 * missing or structurally incompatible (the caller then drops it).
 */
export function sanitizeUniverse(value: unknown): UniverseSelection | null {
  if (!isRecord(value)) {
    return null;
  }
  if (!isStringArray(value.symbols) || value.symbols.length === 0) {
    return null;
  }
  if (typeof value.start !== "string" || typeof value.end !== "string") {
    return null;
  }
  const result = value.result;
  if (!isRecord(result) || !isStringArray(result.symbols)) {
    return null;
  }
  return {
    symbols: value.symbols,
    selected: isStringArray(value.selected) ? value.selected : value.symbols,
    start: value.start,
    end: value.end,
    filters: sanitizeFilters(value.filters),
    result: result as unknown as UniverseBuildResponse,
  };
}

/** Coerce a stored optimization result, dropping it when it is incompatible. */
export function sanitizeOptimize(value: unknown): OptimizeResult | null {
  if (!isRecord(value)) {
    return null;
  }
  if (!isStringArray(value.symbols) || !isRecord(value.weights) || !isRecord(value.assumptions)) {
    return null;
  }
  return value as unknown as OptimizeResult;
}

/** Coerce a stored chosen portfolio, dropping it when it is incompatible. */
export function sanitizeChosenPortfolio(value: unknown): ChosenPortfolio | null {
  if (!isRecord(value) || value.source !== "optimized" || !isRecord(value.weights)) {
    return null;
  }
  const weights: Record<string, number> = {};
  for (const [code, weight] of Object.entries(value.weights)) {
    if (typeof weight === "number" && Number.isFinite(weight)) {
      weights[code] = weight;
    }
  }
  return Object.keys(weights).length > 0 ? { weights, source: "optimized" } : null;
}

/** Coerce stored settings (camelCase or legacy snake_case) into `UserSettings`. */
export function sanitizeSettings(value: unknown): UserSettings | null {
  if (!isRecord(value)) {
    return null;
  }
  const fee = value.brokerageFeeRate ?? value.brokerage_fee_rate;
  const riskFree = value.riskFreeRate ?? value.risk_free_rate;
  if (typeof fee !== "number" || !Number.isFinite(fee) || fee < 0) {
    return null;
  }
  if (typeof riskFree !== "number" || !Number.isFinite(riskFree) || riskFree < 0) {
    return null;
  }
  return { brokerageFeeRate: fee, riskFreeRate: riskFree };
}

function sanitizeLibrary(value: unknown): PortfolioLibrary {
  if (!isRecord(value)) {
    return { portfolios: [], active_id: null };
  }
  const portfolios = sanitizeNamedPortfolios(value.portfolios);
  const activeId =
    typeof value.active_id === "string" && portfolios.some((item) => item.id === value.active_id)
      ? value.active_id
      : null;
  return { portfolios, active_id: activeId };
}

/**
 * Fill the working portfolio from the active saved snapshot when the working
 * copy is empty. Editing a loaded snapshot therefore survives a reload instead
 * of being overwritten.
 */
export function resolveWorkingPortfolio(state: AppState): Portfolio {
  if (state.portfolio.holdings.length > 0 || state.portfolio.cash > 0) {
    return state.portfolio;
  }
  const active = state.library.portfolios.find((item) => item.id === state.library.active_id);
  return active !== undefined ? active.portfolio : state.portfolio;
}

/** Coerce a stored V2 filter into the current shape, using the defaults. */
export function sanitizeV2Filter(value: unknown): UniverseFilterState {
  if (!isRecord(value)) {
    return { ...DEFAULT_V2_FILTER, sectors: [], indexes: [] };
  }
  const weighting =
    value.weighting === "equal" || value.weighting === "market_cap"
      ? value.weighting
      : DEFAULT_V2_FILTER.weighting;
  const capPercent =
    value.capPercent === null
      ? null
      : typeof value.capPercent === "number" &&
          Number.isFinite(value.capPercent) &&
          value.capPercent > 0 &&
          value.capPercent <= 100
        ? value.capPercent
        : DEFAULT_V2_FILTER.capPercent;
  return {
    preset: isLiquidityPresetId(value.preset) ? value.preset : DEFAULT_V2_FILTER.preset,
    sectors: isStringArray(value.sectors) ? [...value.sectors] : [],
    indexes: isStringArray(value.indexes) ? [...value.indexes] : [],
    exchange: typeof value.exchange === "string" ? value.exchange : null,
    benchmark:
      typeof value.benchmark === "string" && value.benchmark
        ? value.benchmark
        : DEFAULT_V2_FILTER.benchmark,
    excludeAdjustmentFlagged: value.excludeAdjustmentFlagged === true,
    weighting,
    capPercent,
    includeDefaultExcluded: value.includeDefaultExcluded === true,
  };
}

/** Coerce stored timeframes into the current shape, using the defaults. */
export function sanitizeTimeframes(value: unknown): Timeframes {
  const record = isRecord(value) ? value : {};
  return {
    optimize: sanitizeTimeframe(record.optimize, DEFAULT_OPTIMIZE_TIMEFRAME),
    risk: sanitizeTimeframe(record.risk, DEFAULT_RISK_TIMEFRAME),
    sector: sanitizeSectorTimeframe(record.sector),
  };
}

function sanitizeAppState(record: Record<string, unknown>): AppState {
  const state: AppState = {
    portfolio: sanitizePortfolio(record.portfolio) ?? EMPTY_PORTFOLIO,
    library: sanitizeLibrary(record.library),
    universe: sanitizeUniverse(record.universe),
    v2Filter: sanitizeV2Filter(record.v2Filter),
    optimize: sanitizeOptimize(record.optimize),
    chosenPortfolio: sanitizeChosenPortfolio(record.chosenPortfolio),
    settings: sanitizeSettings(record.settings),
    timeframes: sanitizeTimeframes(record.timeframes),
  };
  state.portfolio = resolveWorkingPortfolio(state);
  return state;
}

function migrateLegacy(storage: KeyValueStorage): AppState {
  const state = emptyAppState();
  const sanitizedPortfolio = sanitizePortfolio(parseJson(read(storage, LEGACY_PORTFOLIO_KEY)));
  if (sanitizedPortfolio !== null) {
    state.portfolio = sanitizedPortfolio;
  }
  state.library = sanitizeLibrary(parseJson(read(storage, LEGACY_LIBRARY_KEY)));
  state.settings = sanitizeSettings(parseJson(read(storage, LEGACY_SETTINGS_KEY)));
  state.portfolio = resolveWorkingPortfolio(state);
  return state;
}

/**
 * Load the shared store from storage.
 *
 * A payload written with a different schema version (or an unreadable one) is
 * discarded and, when present, the legacy per-feature keys are migrated once.
 * The returned object is always a valid `AppState`.
 */
export function loadAppState(storage: KeyValueStorage | null): AppState {
  if (storage === null) {
    return emptyAppState();
  }
  const parsed = parseJson(read(storage, APP_STORAGE_KEY));
  if (
    isRecord(parsed) &&
    typeof parsed.version === "number" &&
    SUPPORTED_SCHEMA_VERSIONS.has(parsed.version)
  ) {
    return sanitizeAppState(parsed);
  }
  return migrateLegacy(storage);
}

/** Persist the whole shared store under one versioned key. */
export function saveAppState(storage: KeyValueStorage | null, state: AppState): void {
  if (storage === null) {
    return;
  }
  try {
    storage.setItem(
      APP_STORAGE_KEY,
      JSON.stringify({ version: APP_STORAGE_SCHEMA_VERSION, ...state }),
    );
  } catch {
    // A full quota must not break the page; the next save retries.
  }
}
