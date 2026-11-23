"use client";

import Link from "next/link";

import { formatPercent, toPercent } from "@/lib/user-settings";
import { useUserSettings } from "@/lib/user-settings-context";

export function SettingsBadge() {
  const { settings, ready } = useUserSettings();

  return (
    <Link
      href="/settings"
      title="Edit your settings"
      className="inline-flex items-center gap-2 rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-600 hover:border-blue-400 hover:text-blue-600 dark:border-gray-700 dark:text-gray-300 dark:hover:text-blue-400"
    >
      <span className="font-medium">Settings</span>
      {ready && settings ? (
        <span>
          Fee {formatPercent(settings.brokerageFeeRate)} &middot; Rf{" "}
          {formatPercent(settings.riskFreeRate)}
        </span>
      ) : (
        <span>Loading&hellip;</span>
      )}
    </Link>
  );
}
