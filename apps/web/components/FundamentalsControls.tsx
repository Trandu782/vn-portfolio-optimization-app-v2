"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Card } from "@/components/ui/Card";
import { inputClass } from "@/components/ui/Field";
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
    <Card className="grid gap-4 sm:grid-cols-3">
      <form onSubmit={handleSubmit} className="space-y-1.5 text-sm">
        <label htmlFor="fund-ticker-search" className="block font-medium text-fg">
          Ticker
        </label>
        <div className="relative">
          <input
            id="fund-ticker-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search ticker or company"
            className={`${inputClass} w-full`}
          />
          {suggestions.length > 0 && (
            <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-strong bg-surface text-sm shadow-lg transition-opacity duration-150 ease-unslop">
              {suggestions.map((item) => (
                <li key={item.code}>
                  <button
                    type="button"
                    onClick={() => pick(item.code)}
                    className="flex min-h-[40px] w-full items-center justify-between px-3 py-2 text-left transition-colors duration-150 ease-unslop hover:bg-raised"
                  >
                    <span className="font-mono font-medium text-fg">{item.code}</span>
                    <span className="ml-2 truncate text-xs text-fg-muted">
                      {item.exchange}
                      {item.name ? ` · ${item.name}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <span className="block font-mono text-xs text-fg-muted">
          {symbol ? `Showing ${symbol}` : "No ticker selected yet."}
        </span>
      </form>

      <div className="space-y-1.5 text-sm">
        <span className="flex items-center font-medium text-fg">
          Period
          <InfoTip text="Only trailing twelve months (TTM) is populated for every ticker in the current dataset." />
        </span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Reporting period">
          <button
            type="button"
            aria-pressed="true"
            className="min-h-[36px] rounded-md border border-accent bg-accent px-3 py-1 text-xs font-medium text-white"
          >
            TTM
          </button>
          <button
            type="button"
            disabled
            title="not enough data yet"
            className="min-h-[36px] cursor-not-allowed rounded-md border border-hairline bg-raised px-3 py-1 text-xs text-fg-muted opacity-60"
          >
            Annual
          </button>
          <button
            type="button"
            disabled
            title="not enough data yet"
            className="min-h-[36px] cursor-not-allowed rounded-md border border-hairline bg-raised px-3 py-1 text-xs text-fg-muted opacity-60"
          >
            Quarterly
          </button>
        </div>
        <span className="block text-xs text-fg-muted">
          Annual and quarterly are not comparable yet (not enough data).
        </span>
      </div>

      <div className="space-y-1.5 text-sm">
        <span className="block font-medium text-fg">Peer set</span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Peer set">
          {PEER_OPTIONS.map((option) => {
            const active = option.id === peerVariant;
            return (
              <button
                key={option.id}
                type="button"
                title={option.tip}
                aria-pressed={active}
                onClick={() => onPeerVariant(option.id)}
                className={`min-h-[36px] rounded-md border px-3 py-1 text-xs font-medium transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                  active
                    ? "border-accent bg-accent text-white"
                    : "border-strong bg-raised text-fg-secondary hover:bg-surface hover:text-fg"
                }`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <span className="block text-xs text-fg-muted">
          The peer set never crosses sectors, so banks are never compared with non-financials.
        </span>
      </div>
    </Card>
  );
}
