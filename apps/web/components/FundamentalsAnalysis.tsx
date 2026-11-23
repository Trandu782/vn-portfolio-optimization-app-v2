"use client";

/**
 * Sector Analysis | Fundamentals sub-tab body (docs/V2_SPEC.md section 3.3).
 *
 * A ticker search drives an inline detail view (scorecard, table, box plot and the
 * period/provider/data-as-of metadata). The selected peer variant is page-local;
 * the active liquidity preset comes from the shared V2 filter so the "liquidity
 * preset" peer set matches the Optimize tab. The same detail is reusable inside the
 * ticker drawer opened from the Optimize results.
 */

import { useState } from "react";

import type { PeerVariant } from "@/lib/api";
import { useAppStore } from "@/lib/app-store-context";

import { Disclaimer } from "./Disclaimer";
import { FundamentalsControls } from "./FundamentalsControls";
import { FundamentalsDetail } from "./FundamentalsDetail";

export function FundamentalsAnalysis() {
  const { v2Filter } = useAppStore();
  const [symbol, setSymbol] = useState<string | null>(null);
  const [peerVariant, setPeerVariant] = useState<PeerVariant>("all");

  return (
    <section className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-300">
        Compare a ticker&apos;s financial ratios with its ICB level-2 sector. The median is
        the primary comparison; direction-aware colouring marks what is better, similar or
        worse. Financials are only compared with their own group.
      </p>

      <FundamentalsControls
        symbol={symbol}
        peerVariant={peerVariant}
        onSymbol={setSymbol}
        onPeerVariant={setPeerVariant}
      />

      <FundamentalsDetail
        symbol={symbol}
        peerVariant={peerVariant}
        preset={v2Filter.preset}
      />

      <Disclaimer context="Fundamentals comparison" verb="is" />
    </section>
  );
}
