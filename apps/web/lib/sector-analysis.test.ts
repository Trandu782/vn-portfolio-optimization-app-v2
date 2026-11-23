import assert from "node:assert/strict";
import { test } from "node:test";

import {
  analyticsViewState,
  benchmarkLabel,
  capOffWarning,
  correlationColor,
  isCorrelationMatrixValid,
  isRowGreyed,
  isRowSelectable,
  orderedHeatmap,
  rowBadge,
  sectorColor,
  SECTOR_COLORS,
  sortSectorRows,
  summarizeExcluded,
  toExcludedView,
  toSectorRow,
  toggleHidden,
  type SectorRow,
} from "./sector-analysis.ts";
import type { SectorGroupAnalytics } from "./api";

const ROWS: SectorRow[] = [
  { name: "Banks", periodReturn: 10, excessReturn: 4, beta: 1.1, rSquared: 0.8, volatility: 20, constituentCount: 8, defaultExcludedCount: 1, status: "ok", lowReliability: false, capOff: false, capOffReason: null },
  { name: "Technology", periodReturn: 18, excessReturn: 12, beta: 1.3, rSquared: 0.6, volatility: 30, constituentCount: 5, defaultExcludedCount: 0, status: "ok", lowReliability: true, capOff: false, capOffReason: null },
  { name: "Utilities", periodReturn: null, excessReturn: null, beta: null, rSquared: null, volatility: null, constituentCount: 2, defaultExcludedCount: 0, status: "insufficient", lowReliability: true, capOff: false, capOffReason: null },
];

test("sorting by beta descending orders ok rows and keeps insufficient last", () => {
  const sorted = sortSectorRows(ROWS, "beta", "desc");
  assert.deepEqual(sorted.map((row) => row.name), ["Technology", "Banks", "Utilities"]);
});

test("sorting puts null values last", () => {
  const sorted = sortSectorRows(ROWS, "period_return", "asc");
  assert.equal(sorted[sorted.length - 1].name, "Utilities");
});

test("row state helpers classify ok and insufficient", () => {
  assert.equal(isRowSelectable(ROWS[0]), true);
  assert.equal(isRowGreyed(ROWS[0]), false);
  assert.equal(isRowSelectable(ROWS[2]), false);
  assert.equal(isRowGreyed(ROWS[2]), true);
});

test("row badge says too few stocks for greyed rows and low reliability only for short windows", () => {
  assert.deepEqual(rowBadge(ROWS[2]), { label: "Too few stocks (needs 3)", tone: "muted" });
  assert.deepEqual(rowBadge(ROWS[1]), { label: "Low reliability", tone: "warning" });
  assert.equal(rowBadge(ROWS[0]), null);
});

test("heatmap reorders into the clustered order and stays symmetric with a unit diagonal", () => {
  const { labels, matrix } = orderedHeatmap({
    labels: ["A", "B", "C"],
    matrix: [
      [1, 0.2, 0.8],
      [0.2, 1, 0.4],
      [0.8, 0.4, 1],
    ],
    ordered_labels: ["C", "A", "B"],
  });
  assert.deepEqual(labels, ["C", "A", "B"]);
  assert.deepEqual(matrix[0], [1, 0.8, 0.4]);
  assert.equal(isCorrelationMatrixValid(matrix), true);
});

test("an asymmetric matrix is flagged invalid", () => {
  assert.equal(isCorrelationMatrixValid([[1, 0.5], [0.4, 1]]), false);
});

test("legend toggle flips one id", () => {
  assert.deepEqual(toggleHidden({}, "Banks"), { Banks: true });
  assert.deepEqual(toggleHidden({ Banks: true }, "Banks"), { Banks: false });
});

test("excluded summary groups by sector with counts", () => {
  const groups = summarizeExcluded([
    { ticker: "B4", sector: "Banks", severity: "warning", category: "data_glitch", reason: "jump", reasons: ["jump"] },
    { ticker: "B5", sector: "Banks", severity: "warning", category: "data_glitch", reason: "jump", reasons: [] },
    { ticker: "T4", sector: "Technology", severity: "warning", category: "data_glitch", reason: "jump", reasons: [] },
  ]);
  assert.equal(groups[0].sector, "Banks");
  assert.equal(groups[0].tickers.length, 2);
  assert.equal(groups[1].sector, "Technology");
});

test("view state distinguishes loading, unavailable, empty and ready", () => {
  assert.equal(analyticsViewState(true, null, 0), "loading");
  assert.equal(analyticsViewState(false, "no stored price data", 0), "unavailable");
  assert.equal(analyticsViewState(false, "boom", 0), "error");
  assert.equal(analyticsViewState(false, null, 0), "empty");
  assert.equal(analyticsViewState(false, null, 3), "ready");
});

test("capOffWarning finds only the engine's single-stock-cap warning", () => {
  const warning =
    "single-stock cap 15% is infeasible with 4 constituents; weights are left uncapped";
  assert.equal(capOffWarning(["other warning", warning]), warning);
  assert.equal(capOffWarning(undefined), null);
  assert.equal(capOffWarning([]), null);
  assert.equal(capOffWarning(["a different warning"]), null);
});

test("benchmark label maps VNINDEX to VN-Index", () => {
  assert.equal(benchmarkLabel("VNINDEX"), "VN-Index");
  assert.equal(benchmarkLabel("vnindex"), "VN-Index");
  assert.equal(benchmarkLabel("VN30"), "VN30");
  assert.equal(benchmarkLabel("OTHER"), "OTHER");
});

test("sector colours wrap around the palette", () => {
  assert.equal(sectorColor(0), "#2563eb");
  assert.equal(sectorColor(SECTOR_COLORS.length), "#2563eb");
  assert.equal(sectorColor(1), "#16a34a");
});

test("correlation colour is opaque and diverging around a neutral grey", () => {
  assert.equal(correlationColor(0), "rgb(107, 114, 128)");
  assert.match(correlationColor(0.3), /^rgb\(/); // opaque, not rgba/transparent
  const positive = (correlationColor(1).match(/\d+/g) ?? []).map(Number);
  const negative = (correlationColor(-1).match(/\d+/g) ?? []).map(Number);
  assert.ok(positive[0] > positive[2]); // red dominates at +1
  assert.ok(negative[2] > negative[0]); // blue dominates at -1
  assert.equal(correlationColor(5), correlationColor(1)); // clamped to +1
  assert.equal(correlationColor(-5), correlationColor(-1)); // clamped to -1
});

function groupWithWarning(warnings: string[]): SectorGroupAnalytics {
  return {
    index: {
      group: "Banks",
      status: "ok",
      constituent_count: 4,
      constituents: ["A", "B", "C", "D"],
      excluded: {},
      weights: {},
      cumulative_returns: [],
      warnings,
    },
    metrics: {
      group: "Banks",
      benchmark: "VNINDEX",
      period_return: 5,
      excess_return: 2,
      beta: 1.1,
      r_squared: 0.7,
      correlation: 0.84,
      annualized_volatility: 20,
      observation_count: 120,
      constituent_count: 4,
      low_reliability: false,
      warnings: [],
    },
    default_excluded_count: 0,
  } as unknown as SectorGroupAnalytics;
}

test("toSectorRow flags an infeasible single-stock cap from the engine warning", () => {
  const row = toSectorRow(
    groupWithWarning([
      "single-stock cap 15% is infeasible with 4 constituents; weights are left uncapped",
    ]),
  );
  assert.equal(row.capOff, true);
  assert.match(row.capOffReason ?? "", /single-stock cap/);

  const plain = toSectorRow(groupWithWarning([]));
  assert.equal(plain.capOff, false);
  assert.equal(plain.capOffReason, null);
});

test("toExcludedView gives a plain summary with the affected-date count", () => {
  const view = toExcludedView({
    ticker: "GEE",
    sector: "Banks",
    severity: "warning",
    category: "thin_trading",
    reason: "price moved +15.0% then reversed -14.0% over two sessions",
    affected_dates: ["2023-05-15", "2023-05-16"],
    reasons: ["price moved +15.0% then reversed -14.0% over two sessions on 2023-05-15"],
  });
  assert.equal(view.category, "thin_trading");
  assert.equal(view.categoryLabel, "Thin trading");
  assert.equal(view.affectedDates.length, 2);
  assert.match(view.summary, /^Price moved/); // main reason capitalized
  assert.match(view.summary, /2 affected dates/);
  assert.equal(view.details.length, 1);
});

test("toExcludedView falls back to the first detail when no main reason is set", () => {
  const view = toExcludedView({
    ticker: "XYZ",
    sector: "Unknown",
    severity: "warning",
    category: "data_glitch",
    reason: "",
    reasons: ["a detail line on 2024-01-02"],
  });
  assert.equal(view.sector, "Unknown");
  assert.equal(view.categoryLabel, "Data glitch");
  assert.equal(view.affectedDates.length, 0);
  assert.match(view.summary, /detail line/);
});

