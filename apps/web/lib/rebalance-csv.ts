/**
 * Pure CSV helpers for the Rebalance page.
 *
 * - Export the order list so it can be imported into a broker or a spreadsheet:
 *   `symbol,side,lots,shares,reference_price,value,fee,tax`
 * - Import target weights: `symbol,weight_percent`
 *
 * This module has no DOM or React imports, so it is unit-tested with Node's
 * built-in test runner. Holdings CSV import reuses `parseHoldingsCsv` from
 * `portfolio-csv.ts`.
 */

import type { RebalanceOrder } from "./api";
import { isValidTickerSymbol } from "./portfolio.ts";
import { sanitizeCsvCell } from "./portfolio-csv.ts";

export const ORDER_CSV_COLUMNS = [
  "symbol",
  "side",
  "lots",
  "shares",
  "reference_price",
  "value",
  "fee",
  "tax",
] as const;

/** Serialise an order list to CSV (header plus one line per order). */
export function ordersToCsv(orders: readonly RebalanceOrder[]): string {
  const rows = orders.map((order) =>
    [
      sanitizeCsvCell(order.symbol),
      sanitizeCsvCell(order.side),
      sanitizeCsvCell(order.lots),
      sanitizeCsvCell(order.shares),
      sanitizeCsvCell(Math.round(order.reference_price)),
      sanitizeCsvCell(order.value),
      sanitizeCsvCell(order.fee),
      sanitizeCsvCell(order.tax),
    ].join(","),
  );
  return [ORDER_CSV_COLUMNS.join(","), ...rows].join("\n");
}

export const TARGET_WEIGHT_COLUMNS = ["symbol", "weight_percent"] as const;

export interface TargetWeightRow {
  symbol: string;
  weight_percent: number;
}

/** Serialise target weights to CSV (header plus one line per symbol). */
export function targetWeightsToCsv(rows: readonly TargetWeightRow[]): string {
  const lines = rows.map(
    (row) => `${sanitizeCsvCell(row.symbol)},${sanitizeCsvCell(row.weight_percent)}`,
  );
  return [TARGET_WEIGHT_COLUMNS.join(","), ...lines].join("\n");
}

export interface TargetWeightParseResult {
  rows: TargetWeightRow[];
  errors: string[];
}

function cell(row: string, index: number): string {
  return (row.split(",")[index] ?? "").trim();
}

/** Parse `symbol,weight_percent` CSV text, collecting a message for every bad row. */
export function parseTargetWeightsCsv(text: string): TargetWeightParseResult {
  const errors: string[] = [];
  const rows: TargetWeightRow[] = [];
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let firstDataLine = true;

  lines.forEach((raw, index) => {
    const line = raw.trim();
    if (line === "") {
      return;
    }
    const lineNumber = index + 1;
    const isHeader =
      firstDataLine &&
      line.toLowerCase().replace(/\s+/g, "") === TARGET_WEIGHT_COLUMNS.join(",");
    firstDataLine = false;
    if (isHeader) {
      return;
    }

    const symbol = cell(line, 0).toUpperCase();
    if (symbol === "") {
      errors.push(`line ${lineNumber}: symbol is required`);
      return;
    }
    if (!isValidTickerSymbol(symbol)) {
      errors.push(`line ${lineNumber}: symbol "${symbol}" is invalid`);
      return;
    }

    const rawPercent = cell(line, 1);
    if (rawPercent === "") {
      errors.push(`line ${lineNumber}: weight_percent is required`);
      return;
    }
    const percent = Number(rawPercent);
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
      errors.push(`line ${lineNumber}: weight_percent must be between 0 and 100`);
      return;
    }
    rows.push({ symbol, weight_percent: percent });
  });

  return { rows, errors };
}
