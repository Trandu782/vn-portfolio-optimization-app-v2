"use client";

/**
 * Portfolio page: enter holdings and cash once, see current value and weights.
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
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { inputClass } from "@/components/ui/Field";
import { DownloadIcon, UploadIcon } from "@/components/ui/Icons";
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
      setNotice(`Imported ${parsed.holdings.length} holdings from CSV`);
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
      setNotice(`Imported ${portfolio.holdings.length} holdings from JSON`);
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
    setNotice(`Saved portfolio "${name}"`);
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
      setNotice(`Imported ${count} saved portfolios`);
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : "Saved portfolio import failed");
    }
  }

  function handleLibraryExport() {
    downloadTextFile("portfolios.json", exportLibraryJson(), "application/json");
  }

  function handleLoadNamed(id: string, name: string) {
    loadNamedPortfolio(id);
    setNotice(`Loaded "${name}"`);
  }

  function handleDeleteNamed(id: string, name: string) {
    deleteNamedPortfolio(id);
    setNotice(`Deleted "${name}"`);
  }

  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-[28px] leading-[1.15] font-medium tracking-[-0.015em] text-fg">
          Portfolio
        </h1>
        <p className="max-w-3xl text-sm leading-6 text-fg-secondary">
          Enter the stocks you hold (and the ones you want to hold) once. Every other page
          uses this portfolio, so you never retype your holdings. A holding with zero shares
          is a wishlist ticker.
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
        <Button size="sm" onClick={() => csvInputRef.current?.click()}>
          <UploadIcon size={14} />
          Import CSV
        </Button>
        <Button size="sm" onClick={handleCsvExport} disabled={holdings.length === 0}>
          <DownloadIcon size={14} />
          Export CSV
        </Button>
        <Button size="sm" onClick={() => jsonInputRef.current?.click()}>
          <UploadIcon size={14} />
          Import JSON
        </Button>
        <Button
          size="sm"
          onClick={handleJsonExport}
          disabled={holdings.length === 0 && cash === 0}
        >
          <DownloadIcon size={14} />
          Export JSON
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={clear}
          disabled={holdings.length === 0 && cash === 0}
        >
          Clear
        </Button>
        <span className="font-mono text-xs text-fg-muted">
          CSV: symbol, shares, avg_cost, buy_date
        </span>
      </div>

      <Card>
        <h2 className="text-sm font-medium text-fg">Saved portfolios</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Save the current holdings under a name to switch between strategies later. Saved
          portfolios live in this browser and travel with the saved-portfolio JSON export.
        </p>
        <form onSubmit={handleSaveNamed} className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={saveName}
            onChange={(event) => setSaveName(event.target.value)}
            placeholder="Portfolio name"
            maxLength={80}
            className={`${inputClass} w-full sm:w-64`}
          />
          <Button type="submit" size="md" disabled={saveName.trim() === ""}>
            Save current
          </Button>
          <Button type="button" size="md" onClick={() => libraryInputRef.current?.click()}>
            Import saved JSON
          </Button>
          <Button
            type="button"
            size="md"
            onClick={handleLibraryExport}
            disabled={namedPortfolios.length === 0}
          >
            Export saved JSON
          </Button>
        </form>
        {namedPortfolios.length === 0 ? (
          <p className="mt-3 text-xs text-fg-muted">No saved portfolios yet.</p>
        ) : (
          <ul className="mt-4 divide-y divide-hairline text-sm">
            {namedPortfolios.map((entry) => (
              <li
                key={entry.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-fg">{entry.name}</span>
                  {entry.id === activeNamedId ? <Badge tone="accent">active</Badge> : null}
                  <span className="font-mono text-xs tabular-nums text-fg-muted">
                    {entry.portfolio.holdings.length} holdings · cash{" "}
                    {entry.portfolio.cash.toLocaleString("en-US")}
                  </span>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => handleLoadNamed(entry.id, entry.name)}>
                    Load
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleDeleteNamed(entry.id, entry.name)}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-2xl">
        <form onSubmit={handleSearchSubmit} className="space-y-1.5">
          <label htmlFor="portfolio-search" className="block text-sm font-medium text-fg">
            Add a ticker
          </label>
          <div className="relative">
            <input
              id="portfolio-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search ticker or company"
              className={`${inputClass} w-full`}
            />
            {suggestions.length > 0 && (
              <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-strong bg-surface text-sm shadow-lg transition-opacity duration-150 ease-unslop">
                {suggestions.map((symbol) => (
                  <li key={symbol.code}>
                    <button
                      type="button"
                      onClick={() => handleAddSymbol(symbol.code)}
                      className="flex min-h-[40px] w-full items-center justify-between px-3 py-2 text-left transition-colors duration-150 ease-unslop hover:bg-raised"
                    >
                      <span className="font-mono font-medium text-fg">{symbol.code}</span>
                      <span className="ml-2 truncate text-xs text-fg-muted">
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
            <p className="text-xs text-warn">
              Ticker search is unavailable ({symbolsError}); type a code and press Enter to add it.
            </p>
          )}
        </form>

        <div className="space-y-1.5">
          <label htmlFor="portfolio-cash" className="block text-sm font-medium text-fg">
            Cash (VND)
          </label>
          <input
            id="portfolio-cash"
            type="number"
            inputMode="numeric"
            min={0}
            step={1000}
            value={cash === 0 ? "" : String(cash)}
            placeholder="0"
            onChange={(event) => setCash(parseWhole(event.target.value))}
            className={`${inputClass} w-full font-mono tabular-nums sm:w-52`}
          />
        </div>
      </div>

      <HoldingsTable
        holdings={holdings}
        valuationBySymbol={valuationBySymbol}
        evaluation={evaluation}
        loading={loading}
        onUpdate={updateHolding}
        onRemove={removeHolding}
      />

      {importError && <p className="text-sm text-negative">{importError}</p>}
      {error && <p className="text-sm text-negative">Evaluation failed: {error}</p>}
      {notice && <p className="text-sm text-positive">{notice}</p>}

      <p className="text-xs text-fg-muted">
        Values update automatically and feed the{" "}
        <Link href="/pnl" className="text-accent-ink hover:underline">
          P&amp;L
        </Link>
        {", "}
        <Link href="/optimize" className="text-accent-ink hover:underline">
          Optimize
        </Link>
        {", "}
        <Link href="/risk" className="text-accent-ink hover:underline">
          Risk
        </Link>{" "}
        and{" "}
        <Link href="/rebalance" className="text-accent-ink hover:underline">
          Rebalance
        </Link>{" "}
        pages. Decision support only, not financial advice.
      </p>
    </section>
  );
}
