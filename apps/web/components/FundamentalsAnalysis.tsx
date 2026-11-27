"use client";

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
    <section className="space-y-6">
      <p className="max-w-3xl text-sm leading-6 text-fg-secondary">
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
