"use client";

/**
 * The single React provider behind every page.
 *
 * It owns one persisted `AppState` (see `app-store.ts`) plus the derived,
 * non-persisted data (portfolio valuation, settings bounds). Pages consume it
 * through the small selector hooks in `portfolio-context`, `universe-context`,
 * `optimize-context` and `user-settings-context`, so no page keeps its own copy
 * of shared data.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  evaluatePortfolio,
  fetchSettingsMeta,
  type OptimizeResult,
  type PortfolioEvaluation,
  type SettingsMeta,
} from "./api";
import {
  browserStorage,
  emptyAppState,
  loadAppState,
  saveAppState,
  type AppState,
  type ChosenPortfolio,
  type Timeframes,
  type UniverseFilterState,
  type UniverseSelection,
} from "./app-store";
import {
  EMPTY_PORTFOLIO,
  portfolioLibraryFromJson,
  portfolioLibraryToJson,
  removeNamedPortfolio,
  upsertNamedPortfolio,
  type NamedPortfolio,
  type Portfolio,
  type PortfolioHolding,
} from "./portfolio";
import { setActiveSettings, type UserSettings } from "./user-settings";
import type { SectorTimeframeSelection } from "./sector-timeframe";
import type { TimeframeSelection } from "./timeframe";

export interface UserSettingsBounds {
  brokerageFeeRate: { min: number; max: number };
  riskFreeRate: { min: number; max: number };
}

export interface AppStoreValue {
  /** True once the persisted store has been read from the browser. */
  hydrated: boolean;
  // -- active portfolio -----------------------------------------------------
  holdings: PortfolioHolding[];
  cash: number;
  symbols: string[];
  evaluation: PortfolioEvaluation | null;
  totalValue: number | null;
  loading: boolean;
  error: string | null;
  setCash: (cash: number) => void;
  addHolding: (symbol: string, shares?: number, avgCost?: number | null) => void;
  updateHolding: (symbol: string, changes: Partial<Omit<PortfolioHolding, "symbol">>) => void;
  removeHolding: (symbol: string) => void;
  replacePortfolio: (portfolio: Portfolio) => void;
  clear: () => void;
  namedPortfolios: NamedPortfolio[];
  activeNamedId: string | null;
  saveNamedPortfolio: (name: string) => void;
  loadNamedPortfolio: (id: string) => void;
  deleteNamedPortfolio: (id: string) => void;
  exportLibraryJson: () => string;
  importLibraryJson: (text: string) => number;
  // -- universe -------------------------------------------------------------
  selection: UniverseSelection | null;
  setSelection: (selection: UniverseSelection) => void;
  clearSelection: () => void;
  v2Filter: UniverseFilterState;
  setV2Filter: (filter: UniverseFilterState) => void;
  // -- timeframes -----------------------------------------------------------
  timeframes: Timeframes;
  setTimeframe: (tab: "optimize" | "risk", selection: TimeframeSelection) => void;
  setSectorTimeframe: (selection: SectorTimeframeSelection) => void;
  // -- optimization ---------------------------------------------------------
  optimizeResult: OptimizeResult | null;
  setOptimizeResult: (result: OptimizeResult) => void;
  clearOptimizeResult: () => void;
  // -- chosen (optimized) portfolio ----------------------------------------
  chosenPortfolio: ChosenPortfolio | null;
  setChosenPortfolio: (weights: Record<string, number>) => void;
  clearChosenPortfolio: () => void;
  // -- settings -------------------------------------------------------------
  settings: UserSettings | null;
  bounds: UserSettingsBounds | null;
  ready: boolean;
  updateSettings: (next: UserSettings) => void;
  resetSettings: () => void;
}

const AppStoreContext = createContext<AppStoreValue | null>(null);

const EVALUATION_DEBOUNCE_MS = 400;

function withinBounds(value: number, range: { min: number; max: number }): boolean {
  return value >= range.min && value <= range.max;
}

function toBounds(meta: SettingsMeta): UserSettingsBounds {
  return {
    brokerageFeeRate: meta.bounds.brokerage_fee_rate,
    riskFreeRate: meta.bounds.risk_free_rate,
  };
}

function toFallback(meta: SettingsMeta): UserSettings {
  return {
    brokerageFeeRate: meta.defaults.brokerage_fee_rate,
    riskFreeRate: meta.defaults.risk_free_rate,
  };
}

function isValidSettings(settings: UserSettings, bounds: UserSettingsBounds): boolean {
  return (
    withinBounds(settings.brokerageFeeRate, bounds.brokerageFeeRate) &&
    withinBounds(settings.riskFreeRate, bounds.riskFreeRate)
  );
}

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(emptyAppState);
  const [hydrated, setHydrated] = useState(false);
  const [evaluation, setEvaluation] = useState<PortfolioEvaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bounds, setBounds] = useState<UserSettingsBounds | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate once from localStorage after mount so the server-rendered HTML and
  // the first client render match, then flip `hydrated` so nothing overwrites
  // saved data before it has been read.
  useEffect(() => {
    setState(loadAppState(browserStorage()));
    setHydrated(true);
  }, []);

  // Persist the whole store on every change, but only after hydration.
  useEffect(() => {
    if (!hydrated) {
      return;
    }
    saveAppState(browserStorage(), state);
  }, [state, hydrated]);

  // Resolve the user's settings against the API defaults and bounds once.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const meta = await fetchSettingsMeta();
        if (cancelled) {
          return;
        }
        const nextBounds = toBounds(meta);
        const fallback = toFallback(meta);
        setBounds(nextBounds);
        setState((current) => {
          const stored = current.settings;
          const resolved = stored && isValidSettings(stored, nextBounds) ? stored : fallback;
          return current.settings === resolved ? current : { ...current, settings: resolved };
        });
      } catch {
        // Settings stay unset; compute requests then fall back to the API defaults.
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep the non-React `api.ts` cache in sync with the active settings.
  useEffect(() => {
    if (state.settings !== null) {
      setActiveSettings(state.settings);
    }
  }, [state.settings]);

  // Revalue the portfolio (debounced) whenever holdings or cash change.
  useEffect(() => {
    if (!hydrated) {
      return;
    }
    const portfolio = state.portfolio;
    if (timer.current !== null) {
      clearTimeout(timer.current);
    }
    if (portfolio.holdings.length === 0 && portfolio.cash === 0) {
      setEvaluation(null);
      setError(null);
      return;
    }
    timer.current = setTimeout(() => {
      setLoading(true);
      evaluatePortfolio({
        holdings: portfolio.holdings.map((holding) => ({
          symbol: holding.symbol,
          shares: holding.shares,
          avg_cost: holding.avg_cost,
        })),
        cash: portfolio.cash,
      })
        .then((result) => {
          setEvaluation(result);
          setError(null);
        })
        .catch((err: unknown) => {
          setEvaluation(null);
          setError(err instanceof Error ? err.message : "Failed to evaluate portfolio");
        })
        .finally(() => setLoading(false));
    }, EVALUATION_DEBOUNCE_MS);
    return () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
      }
    };
  }, [state.portfolio, hydrated]);

  const setCash = useCallback((cash: number) => {
    const next = Number.isFinite(cash) ? Math.max(0, Math.trunc(cash)) : 0;
    setState((current) =>
      current.portfolio.cash === next
        ? current
        : { ...current, portfolio: { ...current.portfolio, cash: next } },
    );
  }, []);

  const addHolding = useCallback(
    (symbol: string, shares = 0, avgCost: number | null = null) => {
      const code = symbol.trim().toUpperCase();
      if (code === "") {
        return;
      }
      setState((current) => {
        if (current.portfolio.holdings.some((holding) => holding.symbol === code)) {
          return current;
        }
        const holding: PortfolioHolding = {
          symbol: code,
          shares: Math.max(0, Math.trunc(shares)),
          avg_cost: avgCost,
        };
        return {
          ...current,
          portfolio: { ...current.portfolio, holdings: [...current.portfolio.holdings, holding] },
        };
      });
    },
    [],
  );

  const updateHolding = useCallback(
    (symbol: string, changes: Partial<Omit<PortfolioHolding, "symbol">>) => {
      setState((current) => ({
        ...current,
        portfolio: {
          ...current.portfolio,
          holdings: current.portfolio.holdings.map((holding) =>
            holding.symbol === symbol ? { ...holding, ...changes } : holding,
          ),
        },
      }));
    },
    [],
  );

  const removeHolding = useCallback((symbol: string) => {
    setState((current) => ({
      ...current,
      portfolio: {
        ...current.portfolio,
        holdings: current.portfolio.holdings.filter((holding) => holding.symbol !== symbol),
      },
    }));
  }, []);

  const replacePortfolio = useCallback((next: Portfolio) => {
    setState((current) => ({ ...current, portfolio: next }));
  }, []);

  const clear = useCallback(() => {
    setState((current) => ({
      ...current,
      portfolio: EMPTY_PORTFOLIO,
      library: { ...current.library, active_id: null },
    }));
  }, []);

  const saveNamedPortfolio = useCallback((name: string) => {
    setState((current) => ({
      ...current,
      library: upsertNamedPortfolio(current.library, name, current.portfolio),
    }));
  }, []);

  const loadNamedPortfolio = useCallback((id: string) => {
    setState((current) => {
      const entry = current.library.portfolios.find((item) => item.id === id);
      if (entry === undefined) {
        return current;
      }
      return {
        ...current,
        portfolio: entry.portfolio,
        library: { ...current.library, active_id: id },
      };
    });
  }, []);

  const deleteNamedPortfolio = useCallback((id: string) => {
    setState((current) => ({
      ...current,
      library: removeNamedPortfolio(current.library, id),
    }));
  }, []);

  const exportLibraryJson = useCallback(
    () => portfolioLibraryToJson(state.library),
    [state.library],
  );

  const importLibraryJson = useCallback((text: string) => {
    const parsed = portfolioLibraryFromJson(text);
    setState((current) => {
      const active = parsed.portfolios.find((item) => item.id === parsed.active_id);
      return {
        ...current,
        library: parsed,
        portfolio: active !== undefined ? active.portfolio : current.portfolio,
      };
    });
    return parsed.portfolios.length;
  }, []);

  const setSelection = useCallback((selection: UniverseSelection) => {
    setState((current) => ({ ...current, universe: selection }));
  }, []);

  const clearSelection = useCallback(() => {
    setState((current) => ({ ...current, universe: null }));
  }, []);

  const setV2Filter = useCallback((filter: UniverseFilterState) => {
    setState((current) => ({ ...current, v2Filter: { ...filter } }));
  }, []);

  const setTimeframe = useCallback(
    (tab: "optimize" | "risk", selection: TimeframeSelection) => {
      setState((current) => ({
        ...current,
        timeframes: { ...current.timeframes, [tab]: { ...selection } },
      }));
    },
    [],
  );

  const setSectorTimeframe = useCallback((selection: SectorTimeframeSelection) => {
    setState((current) => ({
      ...current,
      timeframes: { ...current.timeframes, sector: { ...selection } },
    }));
  }, []);

  const setOptimizeResult = useCallback((result: OptimizeResult) => {
    setState((current) => ({
      ...current,
      optimize: result,
      chosenPortfolio: { weights: { ...result.weights }, source: "optimized" },
    }));
  }, []);

  const clearOptimizeResult = useCallback(() => {
    setState((current) => ({ ...current, optimize: null }));
  }, []);

  const setChosenPortfolio = useCallback((weights: Record<string, number>) => {
    setState((current) => ({
      ...current,
      chosenPortfolio: { weights: { ...weights }, source: "optimized" },
    }));
  }, []);

  const clearChosenPortfolio = useCallback(() => {
    setState((current) => ({ ...current, chosenPortfolio: null }));
  }, []);

  const updateSettings = useCallback((next: UserSettings) => {
    setActiveSettings(next);
    setState((current) => ({ ...current, settings: next }));
  }, []);

  const resetSettings = useCallback(() => {
    fetchSettingsMeta()
      .then((meta) => {
        const fallback = toFallback(meta);
        setActiveSettings(fallback);
        setState((current) => ({ ...current, settings: fallback }));
      })
      .catch(() => {
        // Ignore; the Settings page surfaces an error when the API is unreachable.
      });
  }, []);

  const holdings = state.portfolio.holdings;
  const symbols = useMemo(() => holdings.map((holding) => holding.symbol), [holdings]);

  const value = useMemo<AppStoreValue>(
    () => ({
      hydrated,
      holdings,
      cash: state.portfolio.cash,
      symbols,
      evaluation,
      totalValue: evaluation?.total_value ?? null,
      loading,
      error,
      setCash,
      addHolding,
      updateHolding,
      removeHolding,
      replacePortfolio,
      clear,
      namedPortfolios: state.library.portfolios,
      activeNamedId: state.library.active_id,
      saveNamedPortfolio,
      loadNamedPortfolio,
      deleteNamedPortfolio,
      exportLibraryJson,
      importLibraryJson,
      selection: state.universe,
      setSelection,
      clearSelection,
      v2Filter: state.v2Filter,
      setV2Filter,
      timeframes: state.timeframes,
      setTimeframe,
      setSectorTimeframe,
      optimizeResult: state.optimize,
      setOptimizeResult,
      clearOptimizeResult,
      chosenPortfolio: state.chosenPortfolio,
      setChosenPortfolio,
      clearChosenPortfolio,
      settings: state.settings,
      bounds,
      ready: state.settings !== null && bounds !== null,
      updateSettings,
      resetSettings,
    }),
    [
      hydrated,
      holdings,
      symbols,
      state.portfolio.cash,
      evaluation,
      loading,
      error,
      setCash,
      addHolding,
      updateHolding,
      removeHolding,
      replacePortfolio,
      clear,
      state.library.portfolios,
      state.library.active_id,
      saveNamedPortfolio,
      loadNamedPortfolio,
      deleteNamedPortfolio,
      exportLibraryJson,
      importLibraryJson,
      state.universe,
      setSelection,
      clearSelection,
      state.v2Filter,
      setV2Filter,
      state.timeframes,
      setTimeframe,
      setSectorTimeframe,
      state.optimize,
      setOptimizeResult,
      clearOptimizeResult,
      state.chosenPortfolio,
      setChosenPortfolio,
      clearChosenPortfolio,
      state.settings,
      bounds,
      updateSettings,
      resetSettings,
    ],
  );

  return (
    <AppStoreContext.Provider value={value}>
      {hydrated ? (
        children
      ) : (
        <div className="p-8 text-sm text-gray-500 dark:text-gray-400">Loading your saved data&hellip;</div>
      )}
    </AppStoreContext.Provider>
  );
}

export function useAppStore(): AppStoreValue {
  const context = useContext(AppStoreContext);
  if (context === null) {
    throw new Error("useAppStore must be used within an AppStoreProvider");
  }
  return context;
}



