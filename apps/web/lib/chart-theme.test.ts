import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDateTick, formatDayMonthTick } from "./chart-theme.ts";

test("formatDateTick shows an unambiguous month and full year", () => {
  assert.equal(formatDateTick("2026-05-20"), "May 2026");
  assert.equal(formatDateTick("2024-11-22"), "Nov 2024");
  assert.equal(formatDateTick("not-a-date"), "not-a-date");
});

test("formatDayMonthTick shows the day and month for short windows", () => {
  assert.equal(formatDayMonthTick("2026-05-20"), "20 May");
  assert.equal(formatDayMonthTick("2024-11-02"), "2 Nov");
  assert.equal(formatDayMonthTick("bad"), "bad");
});
