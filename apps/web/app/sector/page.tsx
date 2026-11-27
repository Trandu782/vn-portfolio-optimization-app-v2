"use client";

import { useState } from "react";

import { FundamentalsAnalysis } from "@/components/FundamentalsAnalysis";
import { SectorAnalysis } from "@/components/SectorAnalysis";

const TABS = [
  { id: "market", label: "Market" },
  { id: "fundamentals", label: "Fundamentals" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function SectorPage() {
  const [tab, setTab] = useState<TabId>("market");

  return (
    <div className="space-y-6">
      <div
        role="tablist"
        aria-label="Sector analysis sub-tabs"
        className="flex gap-1 border-b border-hairline text-sm"
      >
        {TABS.map((item) => {
          const active = item.id === tab;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setTab(item.id)}
              className={`min-h-[44px] md:min-h-0 border-b-2 px-4 py-2.5 text-sm transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                active
                  ? "border-accent font-medium text-fg"
                  : "border-transparent text-fg-secondary hover:text-fg"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {tab === "market" ? <SectorAnalysis /> : <FundamentalsAnalysis />}
    </div>
  );
}
