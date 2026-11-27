import assert from "node:assert/strict";
import { test } from "node:test";

import {
  holdingsToCsv,
  parseHoldingsCsv,
  sanitizeCsvCell,
  type CsvHolding,
} from "./portfolio-csv.ts";

const holdings: CsvHolding[] = [
  { symbol: "VNM", shares: 100, avg_cost: 50000 },
  { symbol: "FPT", shares: 0, avg_cost: null },
  { symbol: "ACB", shares: 250, avg_cost: 31000 },
];

test("CSV round trip preserves holdings", () => {
  const parsed = parseHoldingsCsv(holdingsToCsv(holdings));
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.holdings, holdings);
});

test("CSV without a header parses", () => {
  const parsed = parseHoldingsCsv("vnm,100,50000\nFPT,0,");
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.holdings, [
    { symbol: "VNM", shares: 100, avg_cost: 50000 },
    { symbol: "FPT", shares: 0, avg_cost: null },
  ]);
});

test("fractional shares are rejected", () => {
  const parsed = parseHoldingsCsv("VNM,1.5,50000");
  assert.deepEqual(parsed.holdings, []);
  assert.match(parsed.errors[0] ?? "", /whole number/);
});

test("negative shares are rejected", () => {
  const parsed = parseHoldingsCsv("VNM,-1,50000");
  assert.deepEqual(parsed.holdings, []);
  assert.match(parsed.errors[0] ?? "", /must not be negative/);
});

test("empty avg_cost round trips as null", () => {
  const parsed = parseHoldingsCsv(
    holdingsToCsv([{ symbol: "VNM", shares: 10, avg_cost: null }]),
  );
  assert.equal(parsed.holdings[0]?.avg_cost, null);
});

test("buy_date round trips through CSV", () => {
  const row: CsvHolding = {
    symbol: "VNM",
    shares: 100,
    avg_cost: 50000,
    buy_date: "2023-01-05",
  };
  const parsed = parseHoldingsCsv(holdingsToCsv([row]));
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.holdings, [row]);
});

test("an invalid buy_date is rejected", () => {
  const parsed = parseHoldingsCsv("VNM,100,50000,2023-13-40");
  assert.deepEqual(parsed.holdings, []);
  assert.match(parsed.errors[0] ?? "", /buy_date must be YYYY-MM-DD/);
});

test("a legacy three-column header is still accepted", () => {
  const parsed = parseHoldingsCsv("symbol,shares,avg_cost\nvnm,100,50000");
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.holdings, [{ symbol: "VNM", shares: 100, avg_cost: 50000 }]);
});

test("CSV export neutralizes formula-injection prefixes and quotes special characters", () => {
  assert.equal(sanitizeCsvCell("=CMD()"), "'=CMD()");
  assert.equal(sanitizeCsvCell("+1+1"), "'+1+1");
  assert.equal(sanitizeCsvCell("-1+1"), "'-1+1");
  assert.equal(sanitizeCsvCell("@SUM(1,1)"), '"@SUM(1,1)"'.replace("@", "'@"));
  assert.equal(sanitizeCsvCell("\t=1"), "'\t=1");
  assert.equal(sanitizeCsvCell("\r=1"), '"\'\r=1"');
  assert.equal(sanitizeCsvCell('A,"B"'), '"A,""B"""');
  assert.equal(sanitizeCsvCell(-42), "-42");

  const csv = holdingsToCsv([
    { symbol: "=1+1", shares: 10, avg_cost: 1000 },
    { symbol: "+CMD", shares: 20, avg_cost: null },
  ]);
  assert.equal(csv, "symbol,shares,avg_cost,buy_date\n'=1+1,10,1000,\n'+CMD,20,,");
});

test("invalid or formula-like ticker symbols are rejected on CSV parse", () => {
  const parsed = parseHoldingsCsv("=1+1,100,50000\n../etc,10,1000\nVCB?x=1,10,1000");
  assert.deepEqual(parsed.holdings, []);
  assert.equal(parsed.errors.length, 3);
});
