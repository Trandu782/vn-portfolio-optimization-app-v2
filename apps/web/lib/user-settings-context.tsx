"use client";

/**
 * User-settings selector over the single app store.
 *
 * The fee rate and risk-free rate are persisted in the one store (and mirrored
 * into the non-React cache used by the API client); the allowed bounds are
 * fetched from the API and kept in memory.
 */

import type { UserSettings } from "./user-settings";
import { useAppStore, type UserSettingsBounds } from "./app-store-context";

export type { UserSettingsBounds };

export interface UserSettingsContextValue {
  /** Active settings, or null while the defaults are being loaded. */
  settings: UserSettings | null;
  /** Allowed ranges, or null while the defaults are being loaded. */
  bounds: UserSettingsBounds | null;
  /** True once settings and bounds are available. */
  ready: boolean;
  /** Replace the active settings and persist them. */
  updateSettings: (next: UserSettings) => void;
  /** Restore the API defaults and persist them. */
  resetSettings: () => void;
}

export function useUserSettings(): UserSettingsContextValue {
  const { settings, bounds, ready, updateSettings, resetSettings } = useAppStore();
  return { settings, bounds, ready, updateSettings, resetSettings };
}
