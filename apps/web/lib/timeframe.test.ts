import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_RISK_TIMEFRAME,
  MIN_TRADING_DAYS,
  addDays,
  countTradingDays,
  describeWindow,
  resolveTimeframe,
  sanitizeTimeframe,
  validateWindow,
} from "./timeframe.ts";

test("presets count back from the latest data date", () => {
  const resolved = resolveTimeframe({ preset: "3Y", start: "", end: "" }, "2026-11-21");
  assert.equal(resolved.end, "2026-11-21");
  assert.equal(resolved.start, addDays("2026-11-21", -1095));
});

test("a custom selection keeps its explicit dates", () => {
  const resolved = resolveTimeframe(
    { preset: "Custom", start: "2024-01-02", end: "2025-06-30" },
    "2026-11-21",
  );
  assert.deepEqual(resolved, { start: "2024-01-02", end: "2025-06-30" });
});

test("trading days count excludes weekends", () => {
  // 2024-01-01 is a Monday; 2024-01-07 is a Sunday -> five weekdays.
  assert.equal(countTradingDays("2024-01-01", "2024-01-07"), 5);
  assert.equal(countTradingDays("2024-01-07", "2024-01-01"), 0);
});

test("validation rejects short, reversed and future windows", () => {
  assert.match(validateWindow("2024-01-01", "2024-01-10", null) ?? "", /at least/);
  assert.match(
    validateWindow("2024-02-01", "2024-01-01", null) ?? "",
    /before the end/,
  );
  assert.match(
    validateWindow("2023-01-02", "2026-12-31", "2026-11-21") ?? "",
    /after the latest available data/,
  );
  assert.equal(validateWindow("2023-01-02", "2024-01-02", "2026-11-21"), null);
  assert.ok(countTradingDays("2023-01-02", "2024-01-02") >= MIN_TRADING_DAYS);
});

test("describeWindow includes the resolved window and day count", () => {
  const text = describeWindow("2024-01-01", "2024-01-07");
  assert.match(text, /2024-01-01 to 2024-01-07/);
  assert.match(text, /\u2248 5 trading days/);
});

test("sanitizeTimeframe keeps valid values and falls back otherwise", () => {
  assert.deepEqual(
    sanitizeTimeframe({ preset: "2Y", start: "", end: "" }, DEFAULT_RISK_TIMEFRAME),
    { preset: "2Y", start: "", end: "" },
  );
  assert.deepEqual(
    sanitizeTimeframe({ preset: "nope", start: "x" }, DEFAULT_RISK_TIMEFRAME),
    DEFAULT_RISK_TIMEFRAME,
  );
  assert.deepEqual(sanitizeTimeframe(null, DEFAULT_RISK_TIMEFRAME), DEFAULT_RISK_TIMEFRAME);
});
