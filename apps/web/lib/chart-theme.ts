/**
 * Shared Recharts theme and formatters.
 *
 * Every chart imports its colours, axis styling and number/date formatting from
 * here so a future chart looks consistent without copying values around. The
 * colours are fixed rather than theme tokens because Recharts renders SVG, where
 * Tailwind's `dark:` classes do not apply; the chosen greys read on both the
 * white and gray-950 backgrounds of the app.
 */

/** Fixed colours for the known series and markers. */
export const CHART_COLORS = {
  frontier: "#2563eb",
  cloud: "#9ca3af",
  capitalLine: "#0284c7",
  minVariance: "#16a34a",
  tangency: "#ea580c",
  equalWeight: "#6b7280",
  current: "#7c3aed",
  selected: "#1d4ed8",
  drawdown: "#dc2626",
  benchmark: "#6b7280",
} as const;

/** Tick text colour that is legible on both light and dark backgrounds. */
export const AXIS_TEXT = "#6b7280";

/** Subtle gridline colour that works over white and gray-950. */
export const GRID_STROKE = "rgba(107, 114, 128, 0.22)";

/** Shared tick props for both axes. */
export const AXIS_TICK = { fontSize: 11, fill: AXIS_TEXT } as const;

/** Tailwind classes for the HTML tooltip body (dark mode follows the app). */
export const TOOLTIP_CLASS =
  "rounded-md border border-gray-200 bg-white/95 px-2 py-1 text-xs text-gray-900 shadow-md dark:border-gray-700 dark:bg-gray-900/95 dark:text-gray-100";

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
