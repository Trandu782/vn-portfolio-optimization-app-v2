import assert from "node:assert/strict";
import { test } from "node:test";

import { targetRowsFromHoldings, targetRowsFromWeights } from "./rebalance-targets.ts";

test("weights become sorted percent rows and empty entries are dropped", () => {
  const rows = targetRowsFromWeights({
    vnm: 0.25,
    FPT: 0.5,
    EMPTY: 0,
    BAD: Number.NaN,
    " ": 0.1,
  });

  assert.deepEqual(rows, [
    { symbol: "FPT", weight_percent: 50 },
    { symbol: "VNM", weight_percent: 25 },
  ]);
});

test("percentages are truncated so a fully invested mix never exceeds 100%", () => {
  const rows = targetRowsFromWeights({ A: 1 / 3, B: 1 / 3, C: 1 / 3 });

  assert.deepEqual(
    rows.map((row) => row.weight_percent),
    [33.33, 33.33, 33.33],
  );
  const total = rows.reduce((sum, row) => sum + row.weight_percent, 0);
  assert.ok(total <= 100, `expected a total of at most 100, got ${total}`);
});

test("floating point noise does not lose a basis point", () => {
  assert.deepEqual(targetRowsFromWeights({ X: 0.29 }), [
    { symbol: "X", weight_percent: 29 },
  ]);
  assert.deepEqual(targetRowsFromWeights({}), []);
});

test("holdings become target rows, skipping wishlist entries and merging duplicates", () => {
  const rows = targetRowsFromHoldings([
    { symbol: "VNM", shares: 100, weight: 0.4 },
    { symbol: "vnm", shares: 50, weight: 0.1 },
    { symbol: "FPT", shares: 0, weight: 0 },
  ]);

  assert.deepEqual(rows, [{ symbol: "VNM", weight_percent: 50 }]);
});
