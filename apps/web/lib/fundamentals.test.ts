import assert from "node:assert/strict";
import { test } from "node:test";

import {
  INSUFFICIENT_PEERS_LABEL,
  boxPlotStats,
  classifyRatio,
  formatPercentileRank,
  formatRatioValue,
  fundamentalsViewState,
  groupByCategory,
  groupLabel,
  ratioDisplayValue,
  reportingPeriodLabel,
  SIMILAR_TOLERANCE,
  verdictLabel,
  verdictTone,
  type RatioVerdict,
} from "./fundamentals.ts";
import type {
  FundamentalsComparison,
  FundamentalsPeerStatistic,
  FundamentalsRatio,
} from "./api";

function peers(overrides: Partial<FundamentalsPeerStatistic> = {}): FundamentalsPeerStatistic {
  return { n: 10, median: 15, q1: 12, q3: 18, minimum: 8, maximum: 22, ...overrides };
}

function ratio(overrides: Partial<FundamentalsRatio> = {}): FundamentalsRatio {
  return {
    ratio: "roe",
    label: "ROE",
    category: "profitability",
    category_label: "Profitability",
    is_percentage: true,
    direction: "higher",
    not_meaningful: false,
    value: 16,
    peers: peers(),
    ...overrides,
  };
}

test("group labels never say Securities and map every group", () => {
  assert.equal(groupLabel("banks"), "Banks");
  assert.equal(groupLabel("securities"), "Financial services");
  assert.equal(groupLabel("insurance"), "Insurance");
  assert.equal(groupLabel("general"), "General companies");
  assert.equal(groupLabel(null), "General companies");
  assert.equal(groupLabel("mystery"), "General companies");
});

test("ratio formatting keeps percentages on the 0-100 scale and uses n/m for null", () => {
  assert.equal(formatRatioValue(17.3, true), "17.3%");
  assert.equal(formatRatioValue(10, false), "10.00");
  assert.equal(formatRatioValue(null, true), "n/m");
  assert.equal(ratioDisplayValue(ratio({ value: 5 })), "5.0%");
  assert.equal(ratioDisplayValue(ratio({ not_meaningful: true, value: -2 })), "n/m");
  assert.equal(formatPercentileRank(72.4), "72%");
  assert.equal(formatPercentileRank(null), "n/m");
});

test("classifyRatio is direction-aware, treats valuation as neutral and warns on N < 5", () => {
  // Higher is better: clearly above the median.
  assert.equal(classifyRatio(ratio({ value: 20 })), "better");
  assert.equal(classifyRatio(ratio({ value: 10 })), "worse");
  // Within the tolerance of the median.
  const close = 15 * (1 + SIMILAR_TOLERANCE / 2);
  assert.equal(classifyRatio(ratio({ value: close })), "similar");
  // Lower is better (debt/equity): below the median is better.
  assert.equal(
    classifyRatio(ratio({ ratio: "debtEquity", direction: "lower", value: 10 })),
    "better",
  );
  // Valuation multiples stay neutral.
  assert.equal(
    classifyRatio(ratio({ ratio: "pe", direction: "neutral", is_percentage: false, value: 30 })),
    "neutral",
  );
  // Fewer than five peers: warn instead of ranking.
  assert.equal(classifyRatio(ratio({ peers: peers({ n: 4 }) })), "insufficient_peers");
  // Missing / not-meaningful values.
  assert.equal(classifyRatio(ratio({ not_meaningful: true })), "not_meaningful");
  assert.equal(classifyRatio(ratio({ value: null })), "not_meaningful");
});

test("verdict labels are plain language", () => {
  const cases: Array<[RatioVerdict, string]> = [
    ["better", "Better than sector"],
    ["similar", "Similar to sector"],
    ["worse", "Worse than sector"],
    ["neutral", "Valuation (neutral)"],
    ["insufficient_peers", INSUFFICIENT_PEERS_LABEL],
    ["not_meaningful", "n/m"],
  ];
  for (const [verdict, label] of cases) {
    assert.equal(verdictLabel(verdict), label);
  }
  assert.equal(verdictTone("better"), "good");
  assert.equal(verdictTone("worse"), "bad");
  assert.equal(verdictTone("similar"), "warn");
  assert.equal(verdictTone("neutral"), "neutral");
  assert.equal(verdictTone("not_meaningful"), "neutral");
});

test("groupByCategory preserves the ratio-set order and only shows available categories", () => {
  const groups = groupByCategory([
    ratio({ ratio: "roe", category: "profitability", category_label: "Profitability" }),
    ratio({ ratio: "roa", category: "profitability", category_label: "Profitability" }),
    ratio({ ratio: "pe", category: "valuation", category_label: "Valuation", direction: "neutral" }),
  ]);
  assert.deepEqual(
    groups.map((group) => group.categoryLabel),
    ["Profitability", "Valuation"],
  );
  assert.deepEqual(
    groups[0].ratios.map((item) => item.ratio),
    ["roe", "roa"],
  );
});

test("boxPlotStats builds a clamped five-number summary and handles empty peers", () => {
  const stats = boxPlotStats(peers());
  assert.deepEqual(stats, { min: 8, q1: 12, median: 15, q3: 18, max: 22 });
  // Falls back to p5/p95 when quartiles are missing.
  const fallback = boxPlotStats(peers({ q1: null, q3: null, p5: 9, p95: 20 }));
  assert.deepEqual(fallback, { min: 8, q1: 9, median: 15, q3: 20, max: 22 });
  assert.equal(boxPlotStats(peers({ n: 0 })), null);
  assert.equal(boxPlotStats(undefined), null);
});

test("fundamentalsViewState maps 404 to the friendly no-fundamentals state", () => {
  const notFound = Object.assign(new Error("no financial ratios stored for XYZ"), { status: 404 });
  assert.equal(fundamentalsViewState({ loading: true, error: null, comparison: null }), "loading");
  assert.equal(
    fundamentalsViewState({ loading: false, error: notFound, comparison: null }),
    "no_fundamentals",
  );
  assert.equal(
    fundamentalsViewState({ loading: false, error: null, comparison: null }),
    "empty",
  );
  assert.equal(
    fundamentalsViewState({ loading: false, error: new Error("V2 data not available"), comparison: null }),
    "unavailable",
  );
  assert.equal(
    fundamentalsViewState({ loading: false, error: new Error("API responded with 500"), comparison: null }),
    "error",
  );
  const comparison: FundamentalsComparison = {
    symbol: "VCB",
    ratio_group: "banks",
    period: "2026-09-30",
    period_type: "ttm",
    variant: "all",
    ratios: [ratio()],
  };
  assert.equal(
    fundamentalsViewState({ loading: false, error: null, comparison }),
    "ready",
  );
});

test("reportingPeriodLabel spells out the period type", () => {
  assert.equal(reportingPeriodLabel("2026-09-30", "ttm"), "2026-09-30 (trailing twelve months)");
  assert.equal(reportingPeriodLabel("2025-12-31", "annual"), "2025-12-31 (annual)");
  assert.equal(reportingPeriodLabel(null, "ttm"), "latest period");
});
