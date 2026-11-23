"use client";

/**
 * Portfolio selector over the single app store.
 *
 * Holdings, cash, valuation and the named-portfolio library all live in
 * `app-store-context`; this hook exposes only the portfolio slice so pages keep
 * their existing imports.
 */

import { useAppStore } from "./app-store-context";

export function usePortfolio() {
  const store = useAppStore();
  return {
    holdings: store.holdings,
    cash: store.cash,
    symbols: store.symbols,
    evaluation: store.evaluation,
    totalValue: store.totalValue,
    loading: store.loading,
    error: store.error,
    setCash: store.setCash,
    addHolding: store.addHolding,
    updateHolding: store.updateHolding,
    removeHolding: store.removeHolding,
    replacePortfolio: store.replacePortfolio,
    clear: store.clear,
    namedPortfolios: store.namedPortfolios,
    activeNamedId: store.activeNamedId,
    saveNamedPortfolio: store.saveNamedPortfolio,
    loadNamedPortfolio: store.loadNamedPortfolio,
    deleteNamedPortfolio: store.deleteNamedPortfolio,
    exportLibraryJson: store.exportLibraryJson,
    importLibraryJson: store.importLibraryJson,
  };
}
