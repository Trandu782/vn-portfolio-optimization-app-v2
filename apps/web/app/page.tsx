"use client";

import { useEffect, useState } from "react";

type Health =
  | { kind: "loading" }
  | { kind: "ok"; status: string; service: string; version: string }
  | { kind: "error"; message: string };

interface HealthPayload {
  status: string;
  service: string;
  version: string;
}

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
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">VN Portfolio Optimizer</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-300">
          Decision support for Vietnamese equity portfolios. Not financial advice.
        </p>
      </div>

      <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
        <h2 className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
          API health
        </h2>
        <div className="mt-2 text-sm">
          {health.kind === "loading" && <p>Checking the API&hellip;</p>}
          {health.kind === "ok" && (
            <p className="text-green-600 dark:text-green-400">
              {health.status} &mdash; {health.service} v{health.version}
            </p>
          )}
          {health.kind === "error" && (
            <p className="text-red-600 dark:text-red-400">
              Could not reach the API: {health.message}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
