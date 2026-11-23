import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_SECTOR_TIMEFRAME,
  sanitizeSectorTimeframe,
  toSectorRequest,
  validateSectorTimeframe,
} from "./sector-timeframe.ts";

test("presets map to the backend timeframe", () => {
  assert.deepEqual(toSectorRequest({ preset: "6M", start: "", end: "" }), { timeframe: "6M" });
  assert.deepEqual(toSectorRequest({ preset: "YTD", start: "", end: "" }), { timeframe: "YTD" });
});

test("custom maps to the custom keyword with both dates", () => {
  assert.deepEqual(toSectorRequest({ preset: "Custom", start: "2024-01-02", end: "2024-12-31" }), {
    timeframe: "custom",
    custom_start: "2024-01-02",
    custom_end: "2024-12-31",
  });
});

test("validate rejects a custom range without both dates or with start after end", () => {
  assert.equal(
    validateSectorTimeframe({ preset: "Custom", start: "", end: "" }),
    "Choose both a start and an end date.",
  );
  assert.equal(
    validateSectorTimeframe({ preset: "Custom", start: "2024-06-01", end: "2024-05-01" }),
    "The start date must be before the end date.",
  );
  assert.equal(
    validateSectorTimeframe({ preset: "Custom", start: "2024-01-01", end: "2024-12-31" }),
    null,
  );
  assert.equal(validateSectorTimeframe({ preset: "1Y", start: "", end: "" }), null);
});

test("sanitize falls back to the default on bad input and keeps a valid custom range", () => {
  assert.deepEqual(sanitizeSectorTimeframe(null), DEFAULT_SECTOR_TIMEFRAME);
  assert.deepEqual(sanitizeSectorTimeframe({ preset: "2Y" }), DEFAULT_SECTOR_TIMEFRAME);
  assert.deepEqual(
    sanitizeSectorTimeframe({ preset: "Custom", start: "2024-01-01", end: "2024-12-31" }),
    { preset: "Custom", start: "2024-01-01", end: "2024-12-31" },
  );
});
