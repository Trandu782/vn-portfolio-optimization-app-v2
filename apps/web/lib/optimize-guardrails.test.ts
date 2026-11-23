import assert from "node:assert/strict";
import { test } from "node:test";

import {
  HARD_MAX_STOCKS,
  defaultMaxWeight,
  exceedsHardMax,
  feasibleMaxWeight,
  universeSizeWarnings,
} from "./optimize-guardrails.ts";

test("defaultMaxWeight is max(25%, 1.5 / n), capped at 100%", () => {
  assert.equal(defaultMaxWeight(0), 0.25);
  assert.equal(defaultMaxWeight(1), 1);
  assert.equal(defaultMaxWeight(2), 0.75);
  assert.equal(defaultMaxWeight(4), 0.375);
  assert.equal(defaultMaxWeight(6), 0.25);
  assert.equal(defaultMaxWeight(10), 0.25);
});

test("feasibleMaxWeight raises an infeasible cap to 1 / n", () => {
  assert.deepEqual(feasibleMaxWeight(5, 0.3), { value: 0.3, raised: false });
  assert.deepEqual(feasibleMaxWeight(10, 0.05), { value: 0.1, raised: true });
  assert.deepEqual(feasibleMaxWeight(3, 0.2), { value: 1 / 3, raised: true });
});

test("universeSizeWarnings warns below 5 and above 20 stocks", () => {
  assert.deepEqual(universeSizeWarnings(4), [
    "Only 4 stock(s): the efficient frontier is not meaningful below 5.",
  ]);
  assert.deepEqual(universeSizeWarnings(21), [
    "21 stocks is a lot: the sample covariance becomes unreliable above 20.",
  ]);
  assert.deepEqual(universeSizeWarnings(8), []);
});

test("exceedsHardMax flags more than 30 stocks", () => {
  assert.equal(exceedsHardMax(HARD_MAX_STOCKS), false);
  assert.equal(exceedsHardMax(HARD_MAX_STOCKS + 1), true);
});