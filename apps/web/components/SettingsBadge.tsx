"use client";

import Link from "next/link";

import { formatPercent } from "@/lib/user-settings";
import { useUserSettings } from "@/lib/user-settings-context";

export function SettingsBadge() {
  const { settings, ready } = useUserSettings();

  return (
    <Link
      href="/settings"
      title="Edit your settings"
      className="inline-flex min-h-[36px] items-center gap-2 rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs text-fg-secondary transition-colors duration-150 ease-unslop hover:border-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span className="font-medium text-fg">Settings</span>
      {ready && settings ? (
        <span className="font-mono tabular-nums">
          Fee {formatPercent(settings.brokerageFeeRate)} &middot; Rf{" "}
          {formatPercent(settings.riskFreeRate)}
        </span>
      ) : (
        <span>Loading&hellip;</span>
      )}
    </Link>
  );
}
