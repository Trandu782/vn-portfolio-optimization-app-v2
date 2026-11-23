import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { OptimizeBuilder } from "@/components/OptimizeBuilder";
import { SettingsBadge } from "@/components/SettingsBadge";

export const metadata: Metadata = { title: "Optimize" };

export default function OptimizePage() {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Optimize</h1>
        <SettingsBadge />
      </div>
      <Disclaimer context="Optimizer weights" />
      <OptimizeBuilder />
    </section>
  );
}