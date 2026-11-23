/**
 * Timeframe selection for the Optimize and Risk pages.
 *
 * The two pages analyse the same universe over different windows, so each keeps
 * its own selection in the shared store. This module is pure (no React, no DOM)
 * so the window maths and validation are unit-tested with the Node test runner.
 *
 * Trading-day counts are approximated as weekdays (Monday-Friday). Exchange
 * holidays are intentionally not subtracted here: the exact session count comes
 * from the backend universe build, and the "~60 days" rule only needs an
 * approximate guard before the request is sent.
 */

/** The presets offered by the segmented control, plus a custom range. */
export const TIMEFRAME_PRESETS = ["6M", "1Y", "2Y", "3Y", "5Y", "Max", "Custom"] as const;

export type TimeframePreset = (typeof TIMEFRAME_PRESETS)[number];

/** The persisted choice for one tab. `start`/`end` are only used for "Custom". */
export interface TimeframeSelection {
  preset: TimeframePreset;
  /** ISO start date (YYYY-MM-DD); used when `preset` is "Custom". */
  start: string;
  /** ISO end date (YYYY-MM-DD); used when `preset` is "Custom". */
  end: string;
}

/** An explicit, resolved window (always ISO YYYY-MM-DD). */
export interface ResolvedWindow {
  start: string;
  end: string;
}

/** Preset lengths in calendar days. "Max" is a practical ten-year cap. */
export const PRESET_DAYS: Record<Exclude<TimeframePreset, "Custom">, number> = {
  "6M": 182,
  "1Y": 365,
  "2Y": 730,
  "3Y": 1095,
  "5Y": 1825,
  Max: 3650,
};

/** Minimum trading days (weekdays) for a meaningful analysis. */
export const MIN_TRADING_DAYS = 60;

/** Default for the Optimize tab: three years (the previous behaviour). */
export const DEFAULT_OPTIMIZE_TIMEFRAME: TimeframeSelection = {
  preset: "3Y",
  start: "",
  end: "",
};

/** Default for the Risk tab: one year (the previous behaviour). */
export const DEFAULT_RISK_TIMEFRAME: TimeframeSelection = {
  preset: "1Y",
  start: "",
  end: "",
};

function toUtc(iso: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    return null;
  }
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function toIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Today's date as an ISO string (the fallback when no data date is known). */
export function todayIso(): string {
  return toIso(new Date());
}

/** Add `days` calendar days to an ISO date, returning an ISO date. */
export function addDays(iso: string, days: number): string {
  const date = toUtc(iso);
  if (date === null) {
    return iso;
  }
  date.setUTCDate(date.getUTCDate() + days);
  return toIso(date);
}

/**
 * Resolve a store selection to an explicit window.
 *
 * Presets end at the latest available data date (`latestDate`) and count back.
 * "Custom" returns the stored dates unchanged. When `latestDate` is not known
 * yet the caller passes today's date so the control still shows a sensible range.
 */
export function resolveTimeframe(selection: TimeframeSelection, latestDate: string): ResolvedWindow {
  const end = latestDate || todayIso();
  if (selection.preset === "Custom") {
    return { start: selection.start, end: selection.end };
  }
  return { start: addDays(end, -PRESET_DAYS[selection.preset]), end };
}

/** Count weekdays (Mon-Fri) in `[start, end]` inclusive; 0 when invalid. */
export function countTradingDays(start: string, end: string): number {
  const from = toUtc(start);
  const to = toUtc(end);
  if (from === null || to === null || from > to) {
    return 0;
  }
  let days = 0;
  const cursor = new Date(from);
  while (cursor <= to) {
    const weekday = cursor.getUTCDay();
    if (weekday !== 0 && weekday !== 6) {
      days += 1;
    }
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

/**
 * Validate a resolved window before it reaches the API.
 *
 * Returns a plain-language message, or `null` when the window is usable. The
 * rules mirror the product requirements: start before end, end not after the
 * latest data, and at least ~60 trading days.
 */
export function validateWindow(
  start: string,
  end: string,
  latestDate: string | null,
): string | null {
  const from = toUtc(start);
  const to = toUtc(end);
  if (from === null || to === null) {
    return "Choose a valid start and end date.";
  }
  if (from >= to) {
    return "The start date must be before the end date.";
  }
  if (latestDate !== null && latestDate !== "" && end > latestDate) {
    return `The end date is after the latest available data (${latestDate}).`;
  }
  const tradingDays = countTradingDays(start, end);
  if (tradingDays < MIN_TRADING_DAYS) {
    return `This window has about ${tradingDays} trading days; pick at least ${MIN_TRADING_DAYS}.`;
  }
  return null;
}

/** A one-line description of a resolved window, e.g. for the picker. */
export function describeWindow(start: string, end: string): string {
  if (!start || !end) {
    return "Choose a start and end date.";
  }
  const tradingDays = countTradingDays(start, end);
  return `${start} to ${end} \u00b7 \u2248 ${tradingDays} trading days`;
}

/** Coerce a stored value into a valid selection, falling back to `fallback`. */
export function sanitizeTimeframe(value: unknown, fallback: TimeframeSelection): TimeframeSelection {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { ...fallback };
  }
  const record = value as Record<string, unknown>;
  const validPreset =
    typeof record.preset === "string" &&
    (TIMEFRAME_PRESETS as readonly string[]).includes(record.preset);
  if (!validPreset) {
    return { ...fallback };
  }
  return {
    preset: record.preset as TimeframePreset,
    start: typeof record.start === "string" ? record.start : "",
    end: typeof record.end === "string" ? record.end : "",
  };
}
