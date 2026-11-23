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
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label="Sector analysis sub-tabs"
        className="flex gap-1 border-b border-gray-200 text-sm dark:border-gray-800"
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
              className={
                active
                  ? "border-b-2 border-blue-600 px-3 py-2 font-medium text-blue-600 dark:text-blue-400"
                  : "px-3 py-2 text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
              }
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
