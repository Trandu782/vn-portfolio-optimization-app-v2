/**
 * Sector Analysis timeframe control (docs/V2_SPEC.md section 3.2).
 *
 * The Sector tab offers a different preset set from Optimize/Risk (1M, 3M, 6M, YTD,
 * 1Y, 3Y and a custom range). Presets resolve on the server relative to the latest
 * stored trading day; only "Custom" carries explicit start/end dates. This module is
 * pure (no React, no DOM) so the mapping and sanitising are unit-tested.
 */

export const SECTOR_TIMEFRAME_PRESETS = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "Custom"] as const;

export type SectorTimeframePreset = (typeof SECTOR_TIMEFRAME_PRESETS)[number];

export interface SectorTimeframeSelection {
  preset: SectorTimeframePreset;
  /** ISO start date (YYYY-MM-DD); used when `preset` is "Custom". */
  start: string;
  /** ISO end date (YYYY-MM-DD); used when `preset` is "Custom". */
  end: string;
}

export const DEFAULT_SECTOR_TIMEFRAME: SectorTimeframeSelection = {
  preset: "1Y",
  start: "",
  end: "",
};

/** The backend timeframe value and (for custom) the explicit dates. */
export interface SectorTimeframeRequest {
  timeframe: string;
  custom_start?: string;
  custom_end?: string;
}

/** Map the selection to the API request fields. */
export function toSectorRequest(selection: SectorTimeframeSelection): SectorTimeframeRequest {
  if (selection.preset === "Custom") {
    return {
      timeframe: "custom",
      ...(selection.start ? { custom_start: selection.start } : {}),
      ...(selection.end ? { custom_end: selection.end } : {}),
    };
  }
  return { timeframe: selection.preset };
}

/** Validate a custom range before it reaches the API; returns a message or null. */
export function validateSectorTimeframe(selection: SectorTimeframeSelection): string | null {
  if (selection.preset !== "Custom") {
    return null;
  }
  if (!selection.start || !selection.end) {
    return "Choose both a start and an end date.";
  }
  if (selection.start >= selection.end) {
    return "The start date must be before the end date.";
  }
  return null;
}

/** Coerce a stored value into a valid selection, falling back to the default. */
export function sanitizeSectorTimeframe(value: unknown): SectorTimeframeSelection {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { ...DEFAULT_SECTOR_TIMEFRAME };
  }
  const record = value as Record<string, unknown>;
  const validPreset =
    typeof record.preset === "string" &&
    (SECTOR_TIMEFRAME_PRESETS as readonly string[]).includes(record.preset);
  if (!validPreset) {
    return { ...DEFAULT_SECTOR_TIMEFRAME };
  }
  return {
    preset: record.preset as SectorTimeframePreset,
    start: typeof record.start === "string" ? record.start : "",
    end: typeof record.end === "string" ? record.end : "",
  };
}
