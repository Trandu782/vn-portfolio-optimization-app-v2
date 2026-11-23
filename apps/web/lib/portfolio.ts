/**
 * Portfolio state (holdings + cash) plus the named-portfolio library.
 *
 * Persistence lives in `app-store.ts` (one versioned localStorage payload); this
 * module owns the shapes and the sanitizers. The API (`core.portfolio`) stays the
 * single source of truth for validation. Values use the same units as the API
 * (whole shares, whole VND).
 */

export interface PortfolioHolding {
  symbol: string;
  shares: number;
  avg_cost: number | null;
  /** Optional ISO date (YYYY-MM-DD) the holding was bought, for the P&L page. */
  buy_date?: string | null;
}

export interface Portfolio {
  holdings: PortfolioHolding[];
  cash: number;
}

/** Version of the JSON export payload. Bump when the shape changes. */
export const PORTFOLIO_STORAGE_SCHEMA_VERSION = 1;

export const EMPTY_PORTFOLIO: Portfolio = { holdings: [], cash: 0 };

function isWholeAmount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/** True for a real calendar date written as ``YYYY-MM-DD``. */
export function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function sanitizeHolding(value: unknown): PortfolioHolding | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const symbol = typeof record.symbol === "string" ? record.symbol.trim().toUpperCase() : "";
  if (symbol === "") {
    return null;
  }
  const shares = record.shares;
  if (!isWholeAmount(shares)) {
    return null;
  }
  const rawCost = record.avg_cost;
  let avgCost: number | null = null;
  if (rawCost !== null && rawCost !== undefined) {
    if (!isWholeAmount(rawCost)) {
      return null;
    }
    avgCost = rawCost;
  }
  let buyDate: string | null = null;
  const rawBuyDate = record.buy_date;
  if (rawBuyDate !== null && rawBuyDate !== undefined && rawBuyDate !== "") {
    if (!isIsoDate(rawBuyDate)) {
      return null;
    }
    buyDate = rawBuyDate;
  }
  const holding: PortfolioHolding = { symbol, shares, avg_cost: avgCost };
  if (buyDate !== null) {
    holding.buy_date = buyDate;
  }
  return holding;
}

/**
 * Coerce arbitrary parsed JSON into a valid portfolio, dropping invalid holdings
 * and duplicate symbols. Returns `null` only when the value is not an object.
 */
export function sanitizePortfolio(value: unknown): Portfolio | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const cash = isWholeAmount(record.cash) ? record.cash : 0;
  const rawHoldings = Array.isArray(record.holdings) ? record.holdings : [];
  const holdings: PortfolioHolding[] = [];
  const seen = new Set<string>();
  for (const item of rawHoldings) {
    const holding = sanitizeHolding(item);
    if (holding !== null && !seen.has(holding.symbol)) {
      seen.add(holding.symbol);
      holdings.push(holding);
    }
  }
  return { holdings, cash };
}

/** Serialise the portfolio for JSON export (includes the schema version). */
export function portfolioToJson(portfolio: Portfolio): string {
  return JSON.stringify(
    {
      version: PORTFOLIO_STORAGE_SCHEMA_VERSION,
      cash: portfolio.cash,
      holdings: portfolio.holdings,
    },
    null,
    2,
  );
}

/** Parse an exported JSON portfolio, rejecting an unsupported schema version. */
export function portfolioFromJson(text: string): Portfolio {
  const parsed: unknown = JSON.parse(text);
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("Invalid portfolio JSON: expected an object");
  }
  const version = (parsed as Record<string, unknown>).version;
  if (version !== undefined && version !== PORTFOLIO_STORAGE_SCHEMA_VERSION) {
    throw new Error(`Unsupported portfolio schema version: ${String(version)}`);
  }
  const portfolio = sanitizePortfolio(parsed);
  if (portfolio === null) {
    throw new Error("Invalid portfolio JSON");
  }
  return portfolio;
}

// -- Named saved portfolios -------------------------------------------------

/**
 * A named snapshot of the active portfolio. The active portfolio still lives
 * under `vnopt.portfolio`; this library is a separate list so the user can keep
 * several strategies and switch between them without retyping holdings.
 */
export interface NamedPortfolio {
  id: string;
  name: string;
  portfolio: Portfolio;
  updated_at: string;
}

/** The named-portfolio library plus the id of the snapshot last loaded. */
export interface PortfolioLibrary {
  portfolios: NamedPortfolio[];
  active_id: string | null;
}

/** Version of the named-portfolio JSON export payload. */
export const PORTFOLIO_LIBRARY_SCHEMA_VERSION = 1;

const MAX_NAME_LENGTH = 80;

export const EMPTY_LIBRARY: PortfolioLibrary = { portfolios: [], active_id: null };

function newPortfolioId(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi !== undefined && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function resolveActiveId(value: unknown, portfolios: NamedPortfolio[]): string | null {
  return typeof value === "string" && portfolios.some((item) => item.id === value) ? value : null;
}

/** Coerce arbitrary parsed JSON into a valid named-portfolio list. */
export function sanitizeNamedPortfolios(value: unknown): NamedPortfolio[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set<string>();
  const portfolios: NamedPortfolio[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null) {
      continue;
    }
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id.trim() : "";
    const name =
      typeof record.name === "string" ? record.name.trim().slice(0, MAX_NAME_LENGTH) : "";
    const portfolio = sanitizePortfolio(record.portfolio);
    if (id === "" || name === "" || portfolio === null || seen.has(id)) {
      continue;
    }
    seen.add(id);
    portfolios.push({
      id,
      name,
      portfolio,
      updated_at:
        typeof record.updated_at === "string" ? record.updated_at : new Date().toISOString(),
    });
  }
  return portfolios;
}

/** Add a named snapshot, replacing the existing entry with the same name. */
export function upsertNamedPortfolio(
  library: PortfolioLibrary,
  name: string,
  portfolio: Portfolio,
): PortfolioLibrary {
  const trimmed = name.trim().slice(0, MAX_NAME_LENGTH);
  if (trimmed === "") {
    return library;
  }
  const existing = library.portfolios.find(
    (item) => item.name.toLowerCase() === trimmed.toLowerCase(),
  );
  const entry: NamedPortfolio = {
    id: existing?.id ?? newPortfolioId(),
    name: trimmed,
    portfolio,
    updated_at: new Date().toISOString(),
  };
  const portfolios = existing
    ? library.portfolios.map((item) => (item.id === existing.id ? entry : item))
    : [...library.portfolios, entry];
  return { portfolios, active_id: entry.id };
}

/** Remove a named snapshot and clear the active id when it pointed at it. */
export function removeNamedPortfolio(library: PortfolioLibrary, id: string): PortfolioLibrary {
  return {
    portfolios: library.portfolios.filter((item) => item.id !== id),
    active_id: library.active_id === id ? null : library.active_id,
  };
}

/** Serialise the whole library for JSON export. */
export function portfolioLibraryToJson(library: PortfolioLibrary): string {
  return JSON.stringify(
    {
      version: PORTFOLIO_LIBRARY_SCHEMA_VERSION,
      active_id: library.active_id,
      portfolios: library.portfolios,
    },
    null,
    2,
  );
}

/** Parse an exported library, rejecting an unsupported schema version. */
export function portfolioLibraryFromJson(text: string): PortfolioLibrary {
  const parsed: unknown = JSON.parse(text);
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("Invalid portfolio library JSON: expected an object");
  }
  const record = parsed as Record<string, unknown>;
  if (record.version !== undefined && record.version !== PORTFOLIO_LIBRARY_SCHEMA_VERSION) {
    throw new Error(`Unsupported portfolio library schema version: ${String(record.version)}`);
  }
  const portfolios = sanitizeNamedPortfolios(record.portfolios);
  return { portfolios, active_id: resolveActiveId(record.active_id, portfolios) };
}
