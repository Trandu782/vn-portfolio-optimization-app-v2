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
        className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
      >
        Universe: none selected
      </Link>
    );
  }

  return (
    <Link
      href="/optimize"
      title={`${selection.start} to ${selection.end}`}
      className="rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-800 hover:bg-blue-100 dark:bg-blue-950 dark:text-blue-200"
    >
      Universe: {selection.symbols.length} tickers
    </Link>
  );
}