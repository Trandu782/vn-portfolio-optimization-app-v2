import assert from "node:assert/strict";
import { test } from "node:test";

import type { RebalanceOrder } from "./api.ts";
import {
  ordersToCsv,
  parseTargetWeightsCsv,
  targetWeightsToCsv,
} from "./rebalance-csv.ts";

const orders: RebalanceOrder[] = [
  {
    symbol: "VNM",
    side: "sell",
    lots: 2,
    shares: 200,
    reference_price: 50000,
    value: 10000000,
    fee: 15000,
    tax: 10000,
  },
  {
    symbol: "FPT",
    side: "buy",
    lots: 1,
    shares: 100,
    reference_price: 100000,
    value: 10000000,
    fee: 15000,
    tax: 0,
  },
];

test("orders CSV has a header and one row per order", () => {
  const lines = ordersToCsv(orders).split("\n");
  assert.equal(lines[0], "symbol,side,lots,shares,reference_price,value,fee,tax");
  assert.equal(lines.length, 3);
  assert.equal(lines[1], "VNM,sell,2,200,50000,10000000,15000,10000");
  assert.equal(lines[2], "FPT,buy,1,100,100000,10000000,15000,0");
});

test("target weights round trip", () => {
  const rows = [
    { symbol: "VNM", weight_percent: 40 },
    { symbol: "FPT", weight_percent: 35 },
  ];
  const parsed = parseTargetWeightsCsv(targetWeightsToCsv(rows));
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.rows, rows);
});

test("target weights parse without a header and upper-case symbols", () => {
  const parsed = parseTargetWeightsCsv("vnm,40\nFPT,35");
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.rows, [
    { symbol: "VNM", weight_percent: 40 },
    { symbol: "FPT", weight_percent: 35 },
  ]);
});

test("out-of-range weights are rejected", () => {
  const parsed = parseTargetWeightsCsv("VNM,120\nFPT,-1");
  assert.deepEqual(parsed.rows, []);
  assert.match(parsed.errors[0] ?? "", /between 0 and 100/);
});

test("missing symbol or weight is rejected", () => {
  const parsed = parseTargetWeightsCsv(",40\nFPT,");
  assert.equal(parsed.rows.length, 0);
  assert.equal(parsed.errors.length, 2);
});

test("rebalance CSV export neutralizes formula-injection characters and quotes", () => {
  const orderCsv = ordersToCsv([
    {
      symbol: "=HYPERLINK(\"http://evil\")",
      side: "buy",
      lots: 1,
      shares: 100,
      reference_price: 50000,
      value: 5000000,
      fee: 7500,
      tax: 0,
    },
  ]);
  const line = orderCsv.split("\n")[1] ?? "";
  assert.equal(
    line,
    '"\'=HYPERLINK(""http://evil"")",buy,1,100,50000,5000000,7500,0',
  );

  const targetCsv = targetWeightsToCsv([
    { symbol: "+SUM(A1)", weight_percent: 50 },
    { symbol: "@EXEC", weight_percent: 50 },
  ]);
  assert.equal(
    targetCsv,
    "symbol,weight_percent\n'+SUM(A1),50\n'@EXEC,50",
  );
});

test("target weights CSV rejects malformed ticker symbols", () => {
  const parsed = parseTargetWeightsCsv("=1+1,50\nVCB/foo,50");
  assert.deepEqual(parsed.rows, []);
  assert.equal(parsed.errors.length, 2);
});
