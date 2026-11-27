"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ArrowUpRightIcon } from "@/components/ui/Icons";

type Health =
  | { kind: "loading" }
  | { kind: "ok"; status: string; service: string; version: string }
  | { kind: "error"; message: string };

interface HealthPayload {
  status: string;
  service: string;
  version: string;
}

const WORKFLOWS = [
  {
    href: "/portfolio",
    title: "Portfolio",
    description:
      "Enter holdings, share counts, average cost, and cash once to feed every calculation.",
  },
  {
    href: "/pnl",
    title: "P&L",
    description:
      "Track unrealized profit and loss, sell-cost impact, and return versus VN-Index.",
  },
  {
    href: "/optimize",
    title: "Optimize",
    description:
      "Filter a ticker universe and compute the efficient frontier, Max Sharpe, and Min Variance mixes.",
  },
  {
    href: "/sector",
    title: "Sector",
    description:
      "Compare sector relative performance, market betas, and fundamental scorecards.",
  },
  {
    href: "/risk",
    title: "Risk",
    description:
      "Inspect drawdowns, VaR, CVaR, Sharpe, and correlation across up to four portfolios.",
  },
  {
    href: "/rebalance",
    title: "Rebalance",
    description:
      "Translate target weights into 100-share HOSE/HNX lot orders with brokerage fees and sell tax.",
  },
];

export default function HomePage() {
  const [health, setHealth] = useState<Health>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch("/api/v1/health", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`API responded with ${response.status}`);
        }
        const payload = (await response.json()) as HealthPayload;
        if (!cancelled) {
          setHealth({ kind: "ok", ...payload });
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Unknown error";
          setHealth({ kind: "error", message });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="space-y-8">
      <div className="space-y-3">
        <h1 className="text-[28px] leading-[1.15] font-medium tracking-[-0.015em] text-fg">
          VN Portfolio Optimizer
        </h1>
        <p className="max-w-2xl text-sm leading-6 text-fg-secondary">
          Personal portfolio workstation for Vietnamese equities across HOSE, HNX, and UPCoM.
        </p>
        <div className="flex items-center gap-2 pt-1 text-xs text-fg-muted">
          <span
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${
              health.kind === "ok"
                ? "bg-positive"
                : health.kind === "error"
                  ? "bg-negative"
                  : "bg-fg-muted"
            }`}
            aria-hidden="true"
          />
          <span className="font-mono tabular-nums">
            {health.kind === "loading" && "API status: checking"}
            {health.kind === "ok" &&
              `API ${health.status} · ${health.service} v${health.version}`}
            {health.kind === "error" && `API unreachable: ${health.message}`}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {WORKFLOWS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="group flex flex-col justify-between rounded-xl border border-hairline bg-surface p-5 transition-colors duration-150 ease-unslop hover:border-strong hover:bg-raised/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page"
          >
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-base font-medium text-fg">{item.title}</h2>
                <ArrowUpRightIcon
                  size={16}
                  className="text-fg-muted transition-colors duration-150 ease-unslop group-hover:text-fg"
                />
              </div>
              <p className="text-sm leading-5 text-fg-secondary">{item.description}</p>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
