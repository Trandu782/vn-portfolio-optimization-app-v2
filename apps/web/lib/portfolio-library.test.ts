import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EMPTY_LIBRARY,
  portfolioLibraryFromJson,
  portfolioLibraryToJson,
  removeNamedPortfolio,
  sanitizeNamedPortfolios,
  upsertNamedPortfolio,
  type Portfolio,
} from "./portfolio.ts";

const basePortfolio: Portfolio = {
  holdings: [{ symbol: "VNM", shares: 100, avg_cost: 50000 }],
  cash: 1_000_000,
};

test("saving a named portfolio adds it and marks it active", () => {
  const library = upsertNamedPortfolio(EMPTY_LIBRARY, "Core", basePortfolio);
  assert.equal(library.portfolios.length, 1);
  assert.equal(library.portfolios[0]?.name, "Core");
  assert.equal(library.active_id, library.portfolios[0]?.id);
});

test("saving the same name replaces the snapshot without duplicating", () => {
  const first = upsertNamedPortfolio(EMPTY_LIBRARY, "Core", basePortfolio);
  const id = first.portfolios[0]?.id;
  const updated: Portfolio = { holdings: [], cash: 5 };
  const second = upsertNamedPortfolio(first, "core", updated);
  assert.equal(second.portfolios.length, 1);
  assert.equal(second.portfolios[0]?.id, id);
  assert.deepEqual(second.portfolios[0]?.portfolio, updated);
});

test("removing the active portfolio clears the active id", () => {
  const library = upsertNamedPortfolio(EMPTY_LIBRARY, "Core", basePortfolio);
  const id = library.portfolios[0]?.id ?? "";
  const emptied = removeNamedPortfolio(library, id);
  assert.deepEqual(emptied.portfolios, []);
  assert.equal(emptied.active_id, null);
});

test("library JSON round trip preserves every named portfolio", () => {
  const library = upsertNamedPortfolio(EMPTY_LIBRARY, "Core", basePortfolio);
  const parsed = portfolioLibraryFromJson(portfolioLibraryToJson(library));
  assert.deepEqual(parsed.portfolios, library.portfolios);
  assert.equal(parsed.active_id, library.active_id);
});

test("library JSON import rejects an unsupported version", () => {
  assert.throws(
    () => portfolioLibraryFromJson(JSON.stringify({ version: 99, portfolios: [] })),
    /Unsupported portfolio library schema version/,
  );
});

test("invalid and duplicate named portfolios are dropped", () => {
  const entries = sanitizeNamedPortfolios([
    { id: "a", name: "One", portfolio: basePortfolio, updated_at: "2024-01-01T00:00:00Z" },
    { id: "a", name: "Duplicate", portfolio: basePortfolio, updated_at: "2024-01-01T00:00:00Z" },
    { id: "b", name: "  ", portfolio: basePortfolio },
    { id: "c", name: "Bad", portfolio: 42 },
  ]);
  assert.equal(entries.length, 1);
  assert.equal(entries[0]?.name, "One");
});
