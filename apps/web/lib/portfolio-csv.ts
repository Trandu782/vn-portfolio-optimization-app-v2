/**
 * Pure CSV import/export for portfolio holdings.
 *
 * Format (one header line, then one line per holding):
 *
 *     symbol,shares,avg_cost,buy_date
 *     VNM,100,50000,2023-01-05
 *     FPT,0,,
 *
 * ``avg_cost`` and ``buy_date`` are optional; an empty cell means "not provided"
 * (null). ``buy_date`` is an ISO date (YYYY-MM-DD). A holding with zero shares is
 * a wishlist entry. This module has no DOM or React imports, so it can be
 * unit-tested with Node's built-in test runner.
 */

import { isIsoDate, isValidTickerSymbol } from "./portfolio.ts";

const FORMULA_PREFIX_RE = /^[=+\-@\t\r]/;

/**
 * Neutralize spreadsheet formula prefixes on string cells and apply RFC 4180 quoting.
 */
export function sanitizeCsvCell(value: string | number): string {
  const text = String(value);
  const guarded =
    typeof value === "string" && FORMULA_PREFIX_RE.test(text) ? `'${text}` : text;
  if (/[,"\n\r]/.test(guarded)) {
    return `"${guarded.replace(/"/g, '""')}"`;
  }
  return guarded;
}

export interface CsvHolding {
  symbol: string;
  shares: number;
  avg_cost: number | null;
  buy_date?: string | null;
}

export const CSV_COLUMNS = ["symbol", "shares", "avg_cost", "buy_date"] as const;

//: The pre-P&L header, still accepted so older exports import cleanly.
const LEGACY_HEADER = "symbol,shares,avg_cost";

export interface CsvParseResult {
  holdings: CsvHolding[];
  errors: string[];
}

function cell(row: string, index: number): string {
  return (row.split(",")[index] ?? "").trim();
}

function wholeNumber(
  value: string,
  field: string,
  line: number,
  errors: string[],
): number | null {
  if (value === "") {
    errors.push(`line ${line}: ${field} is required`);
    return null;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) {
    errors.push(`line ${line}: ${field} must be a whole number (got "${value}")`);
    return null;
  }
  if (parsed < 0) {
    errors.push(`line ${line}: ${field} must not be negative`);
    return null;
  }
  return parsed;
}

/** Parse CSV text into holdings, collecting a message for every bad row. */
export function parseHoldingsCsv(text: string): CsvParseResult {
  const errors: string[] = [];
  const holdings: CsvHolding[] = [];
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let firstDataLine = true;

  lines.forEach((raw, index) => {
    const line = raw.trim();
    if (line === "") {
      return;
    }
    const lineNumber = index + 1;
    const normalizedHeader = line.toLowerCase().replace(/\s+/g, "");
    const isHeader =
      firstDataLine &&
      (normalizedHeader === CSV_COLUMNS.join(",") || normalizedHeader === LEGACY_HEADER);
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
    const shares = wholeNumber(cell(line, 1), "shares", lineNumber, errors);
    if (shares === null) {
      return;
    }

    let avgCost: number | null = null;
    const avgCostCell = cell(line, 2);
    if (avgCostCell !== "") {
      avgCost = wholeNumber(avgCostCell, "avg_cost", lineNumber, errors);
      if (avgCost === null) {
        return;
      }
    }
    let buyDate: string | null = null;
    const buyDateCell = cell(line, 3);
    if (buyDateCell !== "") {
      if (!isIsoDate(buyDateCell)) {
        errors.push(`line ${lineNumber}: buy_date must be YYYY-MM-DD (got "${buyDateCell}")`);
        return;
      }
      buyDate = buyDateCell;
    }
    const holding: CsvHolding = { symbol, shares, avg_cost: avgCost };
    if (buyDate !== null) {
      holding.buy_date = buyDate;
    }
    holdings.push(holding);
  });

  return { holdings, errors };
}

/** Serialise holdings to CSV text (header plus one line per holding). */
export function holdingsToCsv(holdings: readonly CsvHolding[]): string {
  const rows = holdings.map((holding) =>
    [
      sanitizeCsvCell(holding.symbol),
      sanitizeCsvCell(holding.shares),
      sanitizeCsvCell(holding.avg_cost ?? ""),
      sanitizeCsvCell(holding.buy_date ?? ""),
    ].join(","),
  );
  return [CSV_COLUMNS.join(","), ...rows].join("\n");
}
