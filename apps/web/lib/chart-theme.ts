/**
 * Shared Recharts theme and formatters.
 */

/** Fixed colours for the known series and markers, harmonized with the Graphite palette. */
export const CHART_COLORS = {
  frontier: "#3b82f6",
  cloud: "#71717a",
  capitalLine: "#0ea5e9",
  minVariance: "#4cc38a",
  tangency: "#e0a243",
  equalWeight: "#71717a",
  current: "#8b5cf6",
  selected: "#2563eb",
  drawdown: "#e5484d",
  benchmark: "#71717a",
} as const;

/** Tick text colour that is legible on both light and dark backgrounds. */
export const AXIS_TEXT = "#85858b";

/** Subtle gridline colour that works over light and dark surfaces. */
export const GRID_STROKE = "rgba(133, 133, 139, 0.16)";

/** Shared tick props for both axes. */
export const AXIS_TICK = {
  fontSize: 11,
  fill: AXIS_TEXT,
  fontFamily: "var(--font-mono)",
} as const;

/** Tailwind classes for the HTML tooltip body. */
export const TOOLTIP_CLASS =
  "rounded-lg border border-strong bg-surface/95 px-3 py-2 text-xs text-fg shadow-lg backdrop-blur-sm";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Format a fraction as a whole-percent axis tick ("0.15" -> "15%"). */
export function formatAxisPercent(value: number): string {
  if (!Number.isFinite(value)) return "";
  return `${Math.round(value * 100)}%`;
}

/** Format a fraction as a percentage with `digits` decimals ("0.1234" -> "12.3%"). */
export function formatPercent(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "\u2014";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Format a VND amount compactly for an axis tick ("1200000000" -> "1.2B"). */
export function formatCompactVnd(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return String(Math.round(value));
}

/** Format a signed fraction as a percentage ("-0.05" -> "-5.0%"). */
export function formatSignedPercent(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "\u2014";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

/** Format a growth-of-100 level ("112.4" -> "112.4"). */
export function formatLevel(value: number): string {
  if (!Number.isFinite(value)) return "\u2014";
  return value.toFixed(1);
}

/** Format an ISO date as an unambiguous axis tick ("2024-11-22" -> "Nov 2024"). */
export function formatDateTick(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const month = MONTHS[Number(match[2]) - 1] ?? "";
  return `${month} ${match[1]}`;
}

/** Format an ISO date as a day + month tick for short windows ("2024-11-22" -> "22 Nov"). */
export function formatDayMonthTick(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const month = MONTHS[Number(match[2]) - 1] ?? "";
  return `${Number(match[3])} ${month}`;
}
