/** Shared number formatting for VND amounts and portfolio weights. */

/** Render a VND amount with thousands separators (rounded to whole dong). */
export function formatVnd(value: number): string {
  return `${Math.round(value).toLocaleString("en-US")} VND`;
}

/** Render a portfolio weight (fraction) as a percentage with two decimals. */
export function formatWeight(weight: number): string {
  return `${(weight * 100).toFixed(2)}%`;
}
