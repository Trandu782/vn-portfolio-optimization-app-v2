"use client";

/**
 * Controls for the Fundamentals sub-tab (docs/V2_SPEC.md section 3.3): a ticker
 * search, the period selector and the peer-set toggle.
 *
 * The dataset has fully populated TTM rows for the latest period but only partly
 * filled annual rows and empty quarterly rows, so only TTM is selectable; the other
 * two are disabled with a short "not enough data yet" tooltip. The peer toggle
 * offers the all-peers, active-liquidity-preset and VN100 variants.
 */

import { useEffect, useMemo, useState, type FormEvent } from "react";

import { fetchSymbols, type PeerVariant, type SymbolInfo } from "@/lib/api";

import { InfoTip } from "./InfoTip";

const PEER_OPTIONS: Array<{ id: PeerVariant; label: string; tip: string }> = [
  { id: "all", label: "All peers", tip: "Every ticker in the same ICB level-2 sector." },
  {
    id: "liquidity",
    label: "Liquidity preset",
    tip: "Only same-sector peers that pass the active liquidity preset (set on Optimize).",
  },
  { id: "vn100", label: "VN100", tip: "Only same-sector peers that are VN100 members." },
];

export function FundamentalsControls({
  symbol,
  peerVariant,
  onSymbol,
  onPeerVariant,
}: {
  symbol: string | null;
  peerVariant: PeerVariant;
  onSymbol: (code: string) => void;
  onPeerVariant: (variant: PeerVariant) => void;
}) {
  const [query, setQuery] = useState("");
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);

  useEffect(() => {
    let active = true;
    fetchSymbols()
      .then((payload) => {
        if (active) setSymbols(payload.symbols ?? []);
      })
      .catch(() => {
        // Search degrades to typing a code directly.
      });
    return () => {
      active = false;
    };
  }, []);

  const suggestions = useMemo(() => {
    const text = query.trim().toUpperCase();
    if (!text) return [];
    return symbols
      .filter(
        (item) => item.code.includes(text) || (item.name ?? "").toUpperCase().includes(text),
      )
      .slice(0, 8);
  }, [query, symbols]);

  function pick(code: string) {
    const normalized = code.trim().toUpperCase();
    if (!normalized) return;
    onSymbol(normalized);
    setQuery("");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    pick(query);
  }

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <form onSubmit={handleSubmit} className="block text-sm">
        <label htmlFor="fund-ticker-search" className="block font-medium">
          Ticker
        </label>
        <div className="relative mt-1">
          <input
            id="fund-ticker-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Type a code or name (e.g. VCB)"
            className="w-full rounded-md border border-gray-300 px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
          />
          {suggestions.length > 0 && (
            <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-gray-200 bg-white text-sm shadow dark:border-gray-700 dark:bg-gray-900">
              {suggestions.map((item) => (
                <li key={item.code}>
                  <button
                    type="button"
                    onClick={() => pick(item.code)}
                    className="flex w-full items-center justify-between px-2 py-1 text-left hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    <span className="font-medium">{item.code}</span>
                    <span className="ml-2 truncate text-xs text-gray-500 dark:text-gray-400">
                      {item.exchange}
                      {item.name ? ` · ${item.name}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
          {symbol ? `Showing ${symbol}` : "No ticker selected yet."}
        </span>
      </form>

      <div className="block text-sm">
        <span className="flex items-center font-medium">
          Period
          <InfoTip text="Only trailing twelve months (TTM) is populated for every ticker in the current dataset." />
        </span>
        <div className="mt-1 flex flex-wrap gap-1" role="group" aria-label="Reporting period">
          <button
            type="button"
            aria-pressed="true"
            className="rounded-md border border-blue-600 bg-blue-600 px-2 py-1 text-xs font-medium text-white"
          >
            TTM
          </button>
          <button
            type="button"
            disabled
            title="not enough data yet"
            className="cursor-not-allowed rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-400 dark:border-gray-700 dark:text-gray-500"
          >
            Annual
          </button>
          <button
            type="button"
            disabled
            title="not enough data yet"
            className="cursor-not-allowed rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-400 dark:border-gray-700 dark:text-gray-500"
          >
            Quarterly
          </button>
        </div>
        <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
          Annual and quarterly are not comparable yet (not enough data).
        </span>
      </div>

      <div className="block text-sm">
        <span className="block font-medium">Peer set</span>
        <div className="mt-1 flex flex-wrap gap-1" role="group" aria-label="Peer set">
          {PEER_OPTIONS.map((option) => {
            const active = option.id === peerVariant;
            return (
              <button
                key={option.id}
                type="button"
                title={option.tip}
                aria-pressed={active}
                onClick={() => onPeerVariant(option.id)}
                className={
                  active
                    ? "rounded-md border border-blue-600 bg-blue-600 px-2 py-1 text-xs font-medium text-white"
                    : "rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 dark:border-gray-700 dark:text-gray-200"
                }
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
          The peer set never crosses sectors, so banks are never compared with non-financials.
        </span>
      </div>
    </div>
  );
}
