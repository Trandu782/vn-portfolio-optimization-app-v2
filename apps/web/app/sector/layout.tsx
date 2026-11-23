import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Sector analysis" };

export default function SectorLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">Sector analysis</h1>
      </div>
      {children}
    </div>
  );
}
