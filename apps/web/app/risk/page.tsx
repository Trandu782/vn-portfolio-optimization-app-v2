import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { RiskCalculator } from "@/components/RiskCalculator";
import { SelectedUniverseBadge } from "@/components/SelectedUniverseBadge";
import { SettingsBadge } from "@/components/SettingsBadge";

export const metadata: Metadata = { title: "Risk" };

export default function RiskPage() {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[28px] leading-[1.15] font-medium tracking-[-0.015em] text-fg">
          Risk
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <SelectedUniverseBadge />
          <SettingsBadge />
        </div>
      </div>
      <Disclaimer context="Risk metrics" />
      <RiskCalculator />
    </section>
  );
}
