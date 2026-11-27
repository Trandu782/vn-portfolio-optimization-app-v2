"use client";

import Link from "next/link";

import { useUniverse } from "@/lib/universe-context";

/**
 * Shows the universe selected on the Optimize page. The values come from the
 * shared client store (`lib/universe-context.tsx`), so other pages can reuse the
 * same tickers without re-running the build.
 */
export function SelectedUniverseBadge() {
  const { selection } = useUniverse();

  if (!selection) {
    return (
      <Link
        href="/optimize"
        className="inline-flex min-h-[36px] items-center rounded-md border border-hairline bg-raised px-2.5 py-1 text-xs text-fg-secondary transition-colors duration-150 ease-unslop hover:border-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        Universe: none selected
      </Link>
    );
  }

  return (
    <Link
      href="/optimize"
      title={`${selection.start} to ${selection.end}`}
      className="inline-flex min-h-[36px] items-center rounded-md border border-accent/25 bg-accent-subtle px-2.5 py-1 font-mono text-xs tabular-nums text-accent-ink transition-colors duration-150 ease-unslop hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      Universe: {selection.symbols.length} tickers
    </Link>
  );
}
