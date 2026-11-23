import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { RebalanceCalculator } from "@/components/RebalanceCalculator";
import { SettingsBadge } from "@/components/SettingsBadge";

export const metadata: Metadata = { title: "Rebalance" };

export default function RebalancePage() {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Rebalance</h1>
        <SettingsBadge />
      </div>
      <Disclaimer context="This order list" verb="is" />
      <RebalanceCalculator />
    </section>
  );
}
