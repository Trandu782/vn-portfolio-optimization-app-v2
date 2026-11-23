import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { PortfolioBuilder } from "@/components/PortfolioBuilder";

export const metadata: Metadata = { title: "Portfolio" };

export default function PortfolioPage() {
  return (
    <section className="space-y-4">
      <Disclaimer context="These valuations" />
      <PortfolioBuilder />
    </section>
  );
}
