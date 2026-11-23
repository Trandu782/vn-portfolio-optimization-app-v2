import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { PnLCalculator } from "@/components/PnLCalculator";
import { SettingsBadge } from "@/components/SettingsBadge";

export const metadata: Metadata = { title: "P&L" };

export default function PnLPage() {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">P&amp;L</h1>
        <SettingsBadge />
      </div>
      <Disclaimer context="This profit and loss report" verb="is" />
      <PnLCalculator />
    </section>
  );
}
