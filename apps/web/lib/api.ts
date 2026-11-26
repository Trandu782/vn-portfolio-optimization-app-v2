/**
 * Typed client for the v1 API. Every request that needs the user settings gets
 * them attached automatically from the shared store.
 *
 * The payload types are generated from the FastAPI OpenAPI schema
 * (`apps/web/lib/schema.d.ts`, produced by `make client`), so a change to an API
 * model surfaces as a TypeScript error here. `make check` fails when the
 * generated schema is out of date.
 */

import type { components } from "./schema";

import { getActiveSettings } from "./user-settings";

type Schemas = components["schemas"];

export type SettingsDefaults = Schemas["SettingsDefaults"];
export type ApiSettingsBounds = Schemas["SettingsBounds"];
export type SettingsMeta = Schemas["SettingsResponse"];
export type Assumptions = Schemas["Assumptions"];
export type SharpeResponse = Schemas["SharpeResponse"];
export type CostResponse = Schemas["CostResponse"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const response = await fetch(path, {
    ...init,
    ...(method === "GET" ? {} : { cache: "no-store" as const }),
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`API responded with ${response.status}`);
  }
  return (await response.json()) as T;
}

function withActiveSettings(body: object): Record<string, unknown> {
  const settings = getActiveSettings();
  if (!settings) {
    return { ...body };
  }
  return {
    ...body,
    settings: {
      brokerage_fee_rate: settings.brokerageFeeRate,
      risk_free_rate: settings.riskFreeRate,
    },
  };
}

export function fetchSettingsMeta(): Promise<SettingsMeta> {
  return request<SettingsMeta>("/api/v1/settings");
}

export function computeSharpe(meanReturn: number, volatility: number): Promise<SharpeResponse> {
  return request<SharpeResponse>("/api/v1/risk/sharpe", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ mean_return: meanReturn, volatility })),
  });
}

export function computeCost(notional: number): Promise<CostResponse> {
  return request<CostResponse>("/api/v1/rebalance/cost", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ notional })),
  });
}

export type ProviderStatus = Schemas["ProviderStatus"];

export function fetchProviderStatus(): Promise<ProviderStatus[]> {
  return request<ProviderStatus[]>("/api/v1/data/providers/status");
}

export type DataFreshness = Schemas["DataFreshness"] & {
  latest_date: string | null;
  primary: string | null;
  stale: boolean;
  providers: ProviderStatus[];
};

export function fetchDataFreshness(): Promise<DataFreshness> {
  return request<DataFreshness>("/api/v1/data/freshness");
}

// -- Universe selection -----------------------------------------------------

export type SymbolInfo = Schemas["SymbolInfo"];
export type SymbolListResponse = Schemas["SymbolListResponse"];

export interface ParameterSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  anyOf?: Array<{ type?: string }>;
}

export interface ParameterSchema {
  title?: string;
  type?: string;
  properties?: Record<string, ParameterSchemaProperty>;
  required?: string[];
}

export interface UniverseFilterOption {
  id: string;
  name: string;
  description: string;
  parameter_schema: ParameterSchema | null;
}

export interface UniversePresetOption {
  id: string;
  name: string;
  description: string;
}

export interface UniverseOptions {
  filters: UniverseFilterOption[];
  presets: UniversePresetOption[];
}

export interface UniverseFilterSelection {
  id: string;
  params: Record<string, unknown>;
}

export type QualityFlags = Schemas["QualityFlagsResponse"];
export type DroppedTicker = Schemas["DroppedTickerResponse"];
export type MatrixPayload = Schemas["MatrixResponse"];
export interface UniverseBuildRequest {
  symbols: string[];
  preset?: string | null;
  filters: UniverseFilterSelection[];
  start: string;
  end: string;
  adv_sessions?: number;
}
export type UniverseBuildResponse = Schemas["UniverseBuildResponse"];
export type PresetResponse = Schemas["PresetResponse"];
export type BackfillSymbolResult = Schemas["BackfillSymbolResult"];
export type BackfillResponse = Schemas["BackfillResponse"];

export function fetchSymbols(exchange?: string): Promise<SymbolListResponse> {
  const query = exchange ? `?exchange=${encodeURIComponent(exchange)}` : "";
  return request<SymbolListResponse>(`/api/v1/symbols${query}`);
}

export function fetchUniverseOptions(): Promise<UniverseOptions> {
  return request<UniverseOptions>("/api/v1/universe/options");
}

export function fetchPresetSymbols(indexCode: string): Promise<PresetResponse> {
  return request<PresetResponse>(
    `/api/v1/universe/presets/${encodeURIComponent(indexCode)}`,
  );
}

export function buildUniverse(body: UniverseBuildRequest): Promise<UniverseBuildResponse> {
  return request<UniverseBuildResponse>("/api/v1/universe/build", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function backfillSymbols(symbols: string[]): Promise<BackfillResponse> {
  return request<BackfillResponse>("/api/v1/data/backfill", {
    method: "POST",
    body: JSON.stringify({ symbols }),
  });
}

// -- V2 universe filter & sector list --------------------------------------

export type V2Basis = Schemas["V2Basis"];
export type V2UniverseTicker = Schemas["V2UniverseTicker"];
export type V2UniverseResponse = Schemas["UniverseFilterResponse"];
export type V2SectorCount = Schemas["V2SectorCount"];
export type V2SectorsResponse = Schemas["SectorListResponse"];
export type AdjustmentQualityFlag = Schemas["AdjustmentQualityFlag"];
export type SectorAnalytics = Schemas["AnalyticsResponse"];
export type SectorGroupAnalytics = Schemas["GroupAnalytics"];
export type SectorBenchmarkMetrics = Schemas["BenchmarkMetrics"];
export type SectorGroupIndex = Schemas["GroupIndexResult"];
export type SectorCorrelation = Schemas["CorrelationResult"];
export type SectorReturnPoint = Schemas["ReturnPoint"];
export type SectorDefaultExcluded = Schemas["DefaultExcludedTicker"];

export interface V2UniverseQuery {
  preset?: string;
  sectors?: string[];
  indexes?: string[];
  exchange?: string | null;
  as_of?: string | null;
  exclude_adjustment_flagged?: boolean;
}

export function fetchV2Universe(query: V2UniverseQuery = {}): Promise<V2UniverseResponse> {
  const params = new URLSearchParams();
  if (query.preset) params.set("preset", query.preset);
  for (const sector of query.sectors ?? []) params.append("sectors", sector);
  for (const index of query.indexes ?? []) params.append("indexes", index);
  if (query.exchange) params.set("exchange", query.exchange);
  if (query.as_of) params.set("as_of", query.as_of);
  if (query.exclude_adjustment_flagged) params.set("exclude_adjustment_flagged", "true");
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<V2UniverseResponse>(`/api/v1/v2/universe${suffix}`);
}

export function fetchV2Sectors(preset?: string): Promise<V2SectorsResponse> {
  const query = preset ? `?preset=${encodeURIComponent(preset)}` : "";
  return request<V2SectorsResponse>(`/api/v1/v2/sectors${query}`);
}

// -- Sector Analysis --------------------------------------------------------

export interface SectorAnalyticsQuery {
  benchmark?: string;
  timeframe?: string;
  custom_start?: string;
  custom_end?: string;
  liquidity_preset?: string;
  indexes?: string[];
  exchange?: string | null;
  weighting?: "market_cap" | "equal";
  cap_percent?: number | null;
  include_default_excluded?: boolean;
  exclude_adjustment_flagged?: boolean;
}

/**
 * Fetch the precomputed Sector Analysis payload. A 422 surfaces the server's detail
 * message so the page can tell "no data yet" apart from a genuine request error.
 */
export async function fetchSectorAnalytics(
  query: SectorAnalyticsQuery = {},
): Promise<SectorAnalytics> {
  const params = new URLSearchParams();
  if (query.benchmark) params.set("benchmark", query.benchmark);
  if (query.timeframe) params.set("timeframe", query.timeframe);
  if (query.custom_start) params.set("custom_start", query.custom_start);
  if (query.custom_end) params.set("custom_end", query.custom_end);
  if (query.liquidity_preset) params.set("liquidity_preset", query.liquidity_preset);
  for (const code of query.indexes ?? []) params.append("indexes", code);
  if (query.exchange) params.set("exchange", query.exchange);
  if (query.weighting) params.set("weighting", query.weighting);
  if (typeof query.cap_percent === "number") params.set("cap_percent", String(query.cap_percent));
  if (query.include_default_excluded) params.set("include_default_excluded", "true");
  if (query.exclude_adjustment_flagged) params.set("exclude_adjustment_flagged", "true");
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`/api/v1/v2/analytics${suffix}`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    let detail = `API responded with ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the generic message
    }
    throw new Error(detail);
  }
  return (await response.json()) as SectorAnalytics;
}

// -- Fundamentals (V2b) -----------------------------------------------------

export type FundamentalsComparison = Schemas["FundamentalsComparison"];
export type FundamentalsRatio = Schemas["RatioPeerComparison"];
export type FundamentalsPeerStatistic = Schemas["PeerStatistic"];
export type PeerVariant = "all" | "liquidity" | "vn100";

export interface FundamentalsQuery {
  period?: string;
  period_type?: string;
  peer_variant?: PeerVariant;
  preset?: string;
}

/** Carries the HTTP status so the UI can tell a 404 "no data" from a real error. */
export class FundamentalsRequestError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "FundamentalsRequestError";
    this.status = status;
  }
}

/**
 * Fetch a ticker's ratio comparison against its sector peers.
 *
 * Omitting `period`/`period_type` lets the API pick the ticker's newest stored
 * period (TTM for every ticker in the current dataset). A 404 means the ticker has
 * no stored ratios (the "no fundamentals loaded yet" state), not a request error.
 */
export async function fetchFundamentals(
  symbol: string,
  query: FundamentalsQuery = {},
): Promise<FundamentalsComparison> {
  const params = new URLSearchParams();
  if (query.period) params.set("period", query.period);
  if (query.period_type) params.set("period_type", query.period_type);
  if (query.peer_variant) params.set("peer_variant", query.peer_variant);
  if (query.preset) params.set("preset", query.preset);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(
    `/api/v1/v2/fundamentals/${encodeURIComponent(symbol.trim().toUpperCase())}${suffix}`,
    { headers: { "Content-Type": "application/json" } },
  );
  if (!response.ok) {
    let detail = `API responded with ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the generic message
    }
    throw new FundamentalsRequestError(detail, response.status);
  }
  return (await response.json()) as FundamentalsComparison;
}

// -- Portfolio --------------------------------------------------------------

export type PortfolioHoldingPayload = Schemas["Holding"];
export type PortfolioPayload = Schemas["Portfolio"];
export type PortfolioFreshness = Schemas["Freshness"] & {
  latest_date: string | null;
  stale: boolean;
};
export type HoldingValuation = Schemas["HoldingValuation"] & { warnings: string[] };
export type PortfolioEvaluation = Omit<
  Schemas["PortfolioEvaluationResponse"],
  "holdings" | "warnings"
> & {
  holdings: HoldingValuation[];
  warnings: string[];
};

export function evaluatePortfolio(payload: PortfolioPayload): Promise<PortfolioEvaluation> {
  return request<PortfolioEvaluation>("/api/v1/portfolio/evaluate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// -- Profit and loss --------------------------------------------------------

export type PnLResult = Schemas["PnLResponse"];
export type PnLHolding = Schemas["HoldingPnLResponse"];
export type PnLSummaryResult = Schemas["PnLSummary"];

export function evaluatePnl(
  holdings: Schemas["Holding"][],
  cash: number,
): Promise<PnLResult> {
  return request<PnLResult>("/api/v1/pnl/evaluate", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ holdings, cash })),
  });
}

// -- Optimize ---------------------------------------------------------------

export interface OptimizeOption {
  id: string;
  name: string;
  description: string;
  parameter_schema: ParameterSchema | null;
}

export type OptimizeDefaults = Schemas["OptimizeDefaults"];
export type FrontierDefaults = Schemas["FrontierDefaults"];

export interface OptimizeOptions {
  objectives: OptimizeOption[];
  constraints: OptimizeOption[];
  solvers: OptimizeOption[];
  risk_free_rate_providers: OptimizeOption[];
  defaults: OptimizeDefaults;
  frontier_defaults: FrontierDefaults;
}

export interface OptimizeSelection {
  id: string;
  params: Record<string, unknown>;
}

export interface OptimizeRequest {
  symbols: string[];
  start: string;
  end: string;
  capital: number;
  objective: string;
  constraints: OptimizeSelection[];
  risk_free_rate_provider?: string;
}

export type OptimizeAssumptions = Omit<
  Schemas["AssumptionsResponse"],
  "return_estimator" | "covariance_estimator" | "constraints"
> & {
  return_estimator: { id: string; params: Record<string, unknown> };
  covariance_estimator: { id: string; params: Record<string, unknown> };
  constraints: Array<{ id: string; params: Record<string, unknown> }>;
};

export type OptimizeResult = Omit<Schemas["OptimizeResponse"], "assumptions" | "warnings"> & {
  assumptions: OptimizeAssumptions;
  warnings: string[];
};

export function fetchOptimizeOptions(): Promise<OptimizeOptions> {
  return request<OptimizeOptions>("/api/v1/optimize/options");
}

export function runOptimize(body: OptimizeRequest): Promise<OptimizeResult> {
  return request<OptimizeResult>("/api/v1/optimize", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ ...body })),
  });
}

// -- Efficient frontier -----------------------------------------------------

export type FrontierPoint = Schemas["FrontierPointResponse"];
export type RandomCloudPoint = Schemas["RandomCloudPointResponse"];
export type FrontierAssumptions = Schemas["FrontierAssumptionsResponse"];

export interface FrontierRequest {
  symbols: string[];
  start: string;
  end: string;
  capital: number;
  max_weight?: number;
  max_sector_weight?: number | null;
  sectors?: Record<string, string> | null;
  num_portfolios?: number;
  seed?: number | null;
  current_weights?: Record<string, number>;
  risk_free_rate_provider?: string;
}

export type FrontierResult = Schemas["FrontierResponse"];

export function runFrontier(body: FrontierRequest): Promise<FrontierResult> {
  return request<FrontierResult>("/api/v1/optimize/frontier", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ ...body })),
  });
}

// -- Risk analytics ---------------------------------------------------------

export interface RiskMetricOption {
  id: string;
  name: string;
  description: string;
  parameter_schema: ParameterSchema | null;
}

export interface BenchmarkOption {
  code: string;
  name: string;
  exchange: string;
}

export interface RiskDefaults {
  benchmark: string;
  confidence: number;
}

export interface RiskOptions {
  metrics: RiskMetricOption[];
  benchmarks: BenchmarkOption[];
  defaults: RiskDefaults;
}

export interface RiskRequest {
  weights: Record<string, number>;
  symbols: string[];
  start: string;
  end: string;
  benchmark: string;
  metrics?: string[];
  metric_params?: Record<string, Record<string, unknown>>;
}

export interface VolatilityMetric {
  volatility: number;
}

export interface DrawdownMetric {
  max_drawdown: number;
  dates: string[];
  drawdown: number[];
}

export interface BetaMetric {
  beta: number;
}

export interface ValueAtRiskMetric {
  confidence: number;
  value_at_risk: number;
}

export interface CorrelationMatrixMetric {
  symbols: string[];
  matrix: number[][];
}

export interface SharpeMetric {
  sharpe: number | null;
  mean_return: number;
  volatility: number;
  risk_free_rate: number;
}

export interface TreynorMetric {
  treynor: number | null;
  beta: number | null;
  mean_return: number;
  risk_free_rate: number;
}

export interface JensenAlphaMetric {
  alpha: number | null;
  beta: number | null;
  mean_return: number;
  benchmark_return: number;
  risk_free_rate: number;
}

export type PerformanceResult = Schemas["PerformanceResponse"];

export interface RiskResult {
  symbols: string[];
  weights: Record<string, number>;
  benchmark: string;
  metrics: Record<string, unknown>;
  performance: PerformanceResult;
  assumptions: Assumptions;
  options: RiskMetricOption[];
  warnings: string[];
}

export type RiskPortfolioBlock = Schemas["ComparePortfolioBlock"];

export type RiskCompareResult = Schemas["RiskCompareResponse"];

export interface RiskCompareRequest {
  symbols: string[];
  start: string;
  end: string;
  benchmark: string;
  metrics?: string[];
  metric_params?: Record<string, Record<string, unknown>>;
  current_weights?: Record<string, number> | null;
  optimized_weights?: Record<string, number> | null;
}

export function fetchRiskOptions(): Promise<RiskOptions> {
  return request<RiskOptions>("/api/v1/risk/options");
}

export function computeRisk(body: RiskRequest): Promise<RiskResult> {
  return request<RiskResult>("/api/v1/risk", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ ...body })),
  });
}

export function compareRisk(body: RiskCompareRequest): Promise<RiskCompareResult> {
  return request<RiskCompareResult>("/api/v1/risk/compare", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ ...body })),
  });
}

// -- Rebalance --------------------------------------------------------------

export interface RebalanceOption {
  id: string;
  name: string;
  description: string;
  parameter_schema: ParameterSchema | null;
}

export type RebalanceDefaults = Schemas["RebalanceDefaults"];

export interface RebalanceOptions {
  cost_models: RebalanceOption[];
  policies: RebalanceOption[];
  defaults: RebalanceDefaults;
}

export type RebalancePosition = Schemas["RebalancePositionResponse"];

export type RebalanceSide = "buy" | "sell";

export type RebalanceOrder = Schemas["RebalanceOrderResponse"];
export type RebalanceAssumptions = Schemas["RebalanceAssumptions"];
export type RebalanceResult = Schemas["RebalanceResponse"];
export type RebalanceRequest = Schemas["RebalanceRequest"];

export function fetchRebalanceOptions(): Promise<RebalanceOptions> {
  return request<RebalanceOptions>("/api/v1/rebalance/options");
}

export function runRebalance(body: RebalanceRequest): Promise<RebalanceResult> {
  return request<RebalanceResult>("/api/v1/rebalance", {
    method: "POST",
    body: JSON.stringify(withActiveSettings({ ...body })),
  });
}
