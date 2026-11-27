import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { OptimizeBuilder } from "@/components/OptimizeBuilder";
import { SettingsBadge } from "@/components/SettingsBadge";

export const metadata: Metadata = { title: "Optimize" };

export default function OptimizePage() {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[28px] leading-[1.15] font-medium tracking-[-0.015em] text-fg">
          Optimize
        </h1>
        <SettingsBadge />
      </div>
      <Disclaimer context="Optimizer weights" />
      <OptimizeBuilder />
    </section>
  );
}
