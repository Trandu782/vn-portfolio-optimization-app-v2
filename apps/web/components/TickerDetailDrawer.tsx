"use client";

import { useEffect } from "react";

import { XIcon } from "@/components/ui/Icons";
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
        className="absolute inset-0 cursor-default bg-black/50 backdrop-blur-[2px] transition-opacity duration-150 ease-unslop"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${symbol} fundamentals`}
        className="relative h-full w-full max-w-xl overflow-y-auto overscroll-contain border-l border-hairline bg-surface p-5 pt-[calc(1.25rem+env(safe-area-inset-top))] pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-2xl transition-transform duration-150 ease-unslop"
      >
        <div className="flex items-center justify-between gap-3 border-b border-hairline pb-3">
          <h2 className="text-base font-medium text-fg">
            Fundamentals &middot; <span className="font-mono">{symbol}</span>
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close details"
            className="inline-flex min-h-[40px] min-w-[40px] items-center justify-center rounded-lg text-fg-muted transition-colors duration-150 ease-unslop hover:bg-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent md:min-h-[32px] md:min-w-[32px]"
          >
            <XIcon size={16} />
          </button>
        </div>
        <div className="mt-4">
          <FundamentalsDetail symbol={symbol} peerVariant={peerVariant} preset={preset} />
        </div>
      </div>
    </div>
  );
}
