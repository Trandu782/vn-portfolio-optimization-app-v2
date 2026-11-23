/**
 * User-controlled settings (brokerage fee and risk-free rate).
 *
 * Values are stored as fractions (the same units the API uses) and displayed as
 * percentages. Defaults are never hardcoded here: they are fetched from the API
 * (`GET /api/v1/settings`) so `UserSettings` in `packages/core` stays the single
 * source of truth. Persistence lives in `app-store.ts`.
 */

export interface UserSettings {
  /** Brokerage fee per side as a fraction (0.0015 == 0.15%). */
  brokerageFeeRate: number;
  /** Annual risk-free rate as a fraction (0.03 == 3%). */
  riskFreeRate: number;
}

/** In-memory copy of the active settings, kept in sync by the store. */
let active: UserSettings | null = null;

export function getActiveSettings(): UserSettings | null {
  return active;
}

export function setActiveSettings(settings: UserSettings): void {
  active = settings;
}

export function toPercent(fraction: number): number {
  return fraction * 100;
}

export function fromPercent(percent: number): number {
  return percent / 100;
}

/** Render a fraction as a compact percentage string (0.0015 -> "0.15%"). */
export function formatPercent(fraction: number): string {
  const percent = fraction * 100;
  const formatted = Number.isInteger(percent)
    ? String(percent)
    : percent.toFixed(2).replace(/\.?0+$/, "");
  return `${formatted}%`;
}
