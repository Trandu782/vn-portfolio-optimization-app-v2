"use client";

/**
 * Slide-over ticker detail drawer (docs/V2_SPEC.md section 3.3).
 *
 * Opened from the Optimize results (and usable from search). It hosts the shared
 * `FundamentalsDetail`, so the drawer and the Fundamentals sub-tab always show the
 * same numbers. Escape or a backdrop click closes it.
 */

import { useEffect } from "react";

import type { PeerVariant } from "@/lib/api";

import { FundamentalsDetail } from "./FundamentalsDetail";

export function TickerDetailDrawer({
  symbol,
  onClose,
  peerVariant = "all",
  preset,
}: {
  symbol: string | null;
  onClose: () => void;
  peerVariant?: PeerVariant;
  preset?: string;
}) {
  useEffect(() => {
    if (!symbol) return;
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [symbol, onClose]);

  if (!symbol) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
      <button
        type="button"
        aria-label="Close details"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${symbol} fundamentals`}
        className="relative h-full w-full max-w-xl overflow-y-auto bg-white p-4 shadow-xl dark:bg-gray-950"
      >
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-lg font-semibold">Fundamentals &middot; {symbol}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close details"
            className="rounded-md px-2 py-0.5 text-xl leading-none text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-white"
          >
            &times;
          </button>
        </div>
        <div className="mt-3">
          <FundamentalsDetail symbol={symbol} peerVariant={peerVariant} preset={preset} />
        </div>
      </div>
    </div>
  );
}
