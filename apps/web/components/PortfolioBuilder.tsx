"use client";

/**
 * Portfolio page: enter holdings and cash once, see current value and weights.
 *
 * Tickers are added through the same `/symbols` autocomplete as the Universe page.
 * Each row has a whole-share input (0 == wishlist), an optional average cost and
 * an optional buy date. The live table values everything through the shared
 * `usePortfolio` store, and holdings/cash persist in localStorage. CSV and JSON
 * import/export keep the data portable.
 */

import Link from "next/link";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import { HoldingsTable } from "@/components/HoldingsTable";
import { fetchSymbols, type HoldingValuation, type SymbolInfo } from "@/lib/api";
import { usePortfolio } from "@/lib/portfolio-context";
import { holdingsToCsv, parseHoldingsCsv } from "@/lib/portfolio-csv";
import { portfolioFromJson, portfolioToJson } from "@/lib/portfolio";

const MAX_UPLOAD_BYTES = 1_048_576;

function parseWhole(value: string): number {
  const parsed = Math.trunc(Number(value));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function downloadTextFile(filename: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function PortfolioBuilder() {
  const {
    holdings,
    cash,
    symbols,
    evaluation,
    loading,
    error,
    setCash,
    addHolding,
    updateHolding,
    removeHolding,
    replacePortfolio,
    clear,
    namedPortfolios,
    activeNamedId,
    saveNamedPortfolio,
    loadNamedPortfolio,
    deleteNamedPortfolio,
    exportLibraryJson,
    importLibraryJson,
  } = usePortfolio();

  const [search, setSearch] = useState("");
  const [universeSymbols, setUniverseSymbols] = useState<SymbolInfo[]>([]);
  const [symbolsError, setSymbolsError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("");
  const csvInputRef = useRef<HTMLInputElement>(null);
  const jsonInputRef = useRef<HTMLInputElement>(null);
  const libraryInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    fetchSymbols()
      .then((payload) => {
        if (active) {
          setUniverseSymbols(payload.symbols);
          setSymbolsError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setSymbolsError(err instanceof Error ? err.message : "Failed to load symbols");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const suggestions = useMemo(() => {
    const query = search.trim().toUpperCase();
    if (!query) {
      return [];
    }
    const existing = new Set(symbols);
    return universeSymbols
      .filter(
        (symbol) =>
          symbol.code.includes(query) ||
          (symbol.name ?? "").toUpperCase().includes(query),
      )
      .filter((symbol) => !existing.has(symbol.code))
      .slice(0, 8);
  }, [search, universeSymbols, symbols]);

  const valuationBySymbol = useMemo(() => {
    const map = new Map<string, HoldingValuation>();
    for (const item of evaluation?.holdings ?? []) {
      map.set(item.symbol, item);
    }
    return map;
  }, [evaluation]);

  function handleAddSymbol(raw: string) {
    const code = raw.trim().toUpperCase();
    if (!code) {
      return;
    }
    addHolding(code, 0);
    setSearch("");
    setNotice(null);
  }

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    handleAddSymbol(search);
  }

  async function handleCsvFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setImportError(null);
    setNotice(null);
    if (file.size > MAX_UPLOAD_BYTES) {
      setImportError("CSV import: file is too large (maximum size is 1 MB).");
      return;
    }
    try {
      const parsed = parseHoldingsCsv(await file.text());
      if (parsed.errors.length > 0) {
        setImportError(`CSV import: ${parsed.errors.join("; ")}`);
        return;
      }
      replacePortfolio({ holdings: parsed.holdings, cash });
      setNotice(`Imported ${parsed.holdings.length} holdings from CSV.`);
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : "CSV import failed");
    }
  }

  async function handleJsonFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setImportError(null);
    setNotice(null);
    if (file.size > MAX_UPLOAD_BYTES) {
      setImportError("JSON import: file is too large (maximum size is 1 MB).");
      return;
    }
    try {
      const portfolio = portfolioFromJson(await file.text());
      replacePortfolio(portfolio);
      setNotice(`Imported ${portfolio.holdings.length} holdings from JSON.`);
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : "JSON import failed");
    }
  }

  function handleCsvExport() {
    downloadTextFile("portfolio.csv", holdingsToCsv(holdings), "text/csv");
  }

  function handleJsonExport() {
    downloadTextFile("portfolio.json", portfolioToJson({ holdings, cash }), "application/json");
  }

  function handleSaveNamed(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = saveName.trim();
    if (!name) {
      return;
    }
    saveNamedPortfolio(name);
    setSaveName("");
    setImportError(null);
    setNotice(`Saved portfolio "${name}".`);
  }

  async function handleLibraryFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setImportError(null);
    setNotice(null);
    if (file.size > MAX_UPLOAD_BYTES) {
      setImportError("Saved portfolio import: file is too large (maximum size is 1 MB).");
      return;
    }
    try {
      const count = importLibraryJson(await file.text());
      setNotice(`Imported ${count} saved portfolios.`);
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : "Saved portfolio import failed");
    }
  }

  function handleLibraryExport() {
    downloadTextFile("portfolios.json", exportLibraryJson(), "application/json");
  }

  function handleLoadNamed(id: string, name: string) {
    loadNamedPortfolio(id);
    setNotice(`Loaded "${name}".`);
  }

  function handleDeleteNamed(id: string, name: string) {
    deleteNamedPortfolio(id);
    setNotice(`Deleted "${name}".`);
  }

  const buttonClass =
    "rounded-md border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-900";

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Portfolio</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-300">
          Enter the stocks you hold (and the ones you want to hold) once. Every other page
          uses this portfolio, so you never retype your holdings. A holding with zero shares
          is a wishlist ticker. Average cost is stored only; profit/loss comes in V2.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={csvInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => void handleCsvFile(event)}
          className="hidden"
        />
        <input
          ref={jsonInputRef}
          type="file"
          accept=".json,application/json"
          onChange={(event) => void handleJsonFile(event)}
          className="hidden"
        />
        <input
          ref={libraryInputRef}
          type="file"
          accept=".json,application/json"
          onChange={(event) => void handleLibraryFile(event)}
          className="hidden"
        />
        <button type="button" onClick={() => csvInputRef.current?.click()} className={buttonClass}>
          Import CSV
        </button>
        <button
          type="button"
          onClick={handleCsvExport}
          disabled={holdings.length === 0}
          className={buttonClass}
        >
          Export CSV
        </button>
        <button type="button" onClick={() => jsonInputRef.current?.click()} className={buttonClass}>
          Import JSON
        </button>
        <button
          type="button"
          onClick={handleJsonExport}
          disabled={holdings.length === 0 && cash === 0}
          className={buttonClass}
        >
          Export JSON
        </button>
        <button
          type="button"
          onClick={clear}
          disabled={holdings.length === 0 && cash === 0}
          className={buttonClass}
        >
          Clear
        </button>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          CSV columns: symbol, shares, avg_cost, buy_date (the last two are optional; buy_date is
          YYYY-MM-DD).
        </span>
      </div>

      <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
        <h2 className="text-sm font-medium">Saved portfolios</h2>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          Save the current holdings under a name to switch between strategies later. Saved
          portfolios live in this browser and travel with the saved-portfolio JSON export.
        </p>
        <form onSubmit={handleSaveNamed} className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={saveName}
            onChange={(event) => setSaveName(event.target.value)}
            placeholder="Name this portfolio (e.g. Income)"
            maxLength={80}
            className="w-64 rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
          />
          <button type="submit" disabled={saveName.trim() === ""} className={buttonClass}>
            Save current
          </button>
          <button
            type="button"
            onClick={() => libraryInputRef.current?.click()}
            className={buttonClass}
          >
            Import saved JSON
          </button>
          <button
            type="button"
            onClick={handleLibraryExport}
            disabled={namedPortfolios.length === 0}
            className={buttonClass}
          >
            Export saved JSON
          </button>
        </form>
        {namedPortfolios.length === 0 ? (
          <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
            No saved portfolios yet.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-gray-100 text-sm dark:divide-gray-800">
            {namedPortfolios.map((entry) => (
              <li
                key={entry.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <div>
                  <span className="font-medium">{entry.name}</span>
                  {entry.id === activeNamedId ? (
                    <span className="ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900 dark:text-blue-200">
                      active
                    </span>
                  ) : null}
                  <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                    {entry.portfolio.holdings.length} holdings · cash{" "}
                    {entry.portfolio.cash.toLocaleString()}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleLoadNamed(entry.id, entry.name)}
                    className={buttonClass}
                  >
                    Load
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteNamed(entry.id, entry.name)}
                    className={buttonClass}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form onSubmit={handleSearchSubmit} className="space-y-2">
        <label htmlFor="portfolio-search" className="block text-sm font-medium">
          Add a ticker
        </label>
        <div className="relative">
          <input
            id="portfolio-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Type a code or name (e.g. VNM)"
            className="w-72 rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
          />
          {suggestions.length > 0 && (
            <ul className="absolute z-10 mt-1 max-h-56 w-72 overflow-auto rounded-md border border-gray-200 bg-white text-sm shadow dark:border-gray-700 dark:bg-gray-900">
              {suggestions.map((symbol) => (
                <li key={symbol.code}>
                  <button
                    type="button"
                    onClick={() => handleAddSymbol(symbol.code)}
                    className="flex w-full items-center justify-between px-3 py-1 text-left hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    <span className="font-medium">{symbol.code}</span>
                    <span className="ml-2 truncate text-xs text-gray-500 dark:text-gray-400">
                      {symbol.exchange}
                      {symbol.name ? ` \u00b7 ${symbol.name}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {symbolsError && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Ticker search is unavailable ({symbolsError}); type a code and press Enter to add it.
          </p>
        )}
      </form>

      <label className="block text-sm">
        <span className="block font-medium">Cash (VND)</span>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          step={1000}
          value={cash === 0 ? "" : String(cash)}
          placeholder="0"
          onChange={(event) => setCash(parseWhole(event.target.value))}
          className="mt-1 w-48 rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
        />
      </label>

      <HoldingsTable
        holdings={holdings}
        valuationBySymbol={valuationBySymbol}
        evaluation={evaluation}
        loading={loading}
        onUpdate={updateHolding}
        onRemove={removeHolding}
      />


      {importError && <p className="text-sm text-red-600 dark:text-red-400">{importError}</p>}
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">Evaluation failed: {error}</p>
      )}
      {notice && <p className="text-sm text-green-600 dark:text-green-400">{notice}</p>}

      <p className="text-xs text-gray-500 dark:text-gray-400">
        Values update automatically and feed the{" "}
        <Link href="/pnl" className="text-blue-600 hover:underline dark:text-blue-400">
          P&amp;L
        </Link>
        {", "}
        <Link href="/optimize" className="text-blue-600 hover:underline dark:text-blue-400">
          Optimize
        </Link>
        {", "}
        <Link href="/risk" className="text-blue-600 hover:underline dark:text-blue-400">
          Risk
        </Link>{" "}
        and{" "}
        <Link href="/rebalance" className="text-blue-600 hover:underline dark:text-blue-400">
          Rebalance
        </Link>{" "}
        pages. Decision support only, not financial advice.
      </p>
    </section>
  );
}


