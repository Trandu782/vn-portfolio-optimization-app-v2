import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { RebalanceCalculator } from "@/components/RebalanceCalculator";
import { SettingsBadge } from "@/components/SettingsBadge";

export const metadata: Metadata = { title: "Rebalance" };

export default function RebalancePage() {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[28px] leading-[1.15] font-medium tracking-[-0.015em] text-fg">
          Rebalance
        </h1>
        <SettingsBadge />
      </div>
      <Disclaimer context="This order list" verb="is" />
      <RebalanceCalculator />
    </section>
  );
}
