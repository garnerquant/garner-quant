export interface OverviewApiResponse {
  schema_version: "overview.v1";
  generated_at_utc: string;
  source_as_of_utc: string | null;
  snapshot_freshness: { source_as_of_utc: string | null; snapshot_age_seconds: number | null; freshness_threshold_seconds: number; status: "fresh" | "stale" | "unavailable" };
  source_classification: "local_snapshot" | "partial" | "unavailable";
  warnings: string[];
  portfolio_summary: {
    portfolio_value: string | null;
    cash: string | null;
    daily_change_percent: string | null;
    total_return_percent: string | null;
    latest_recorded_change_as_of_utc: string | null;
  };
  holdings_summary: { holdings: Array<Record<string, string>>; availability: { availability: string; reason?: string } };
  allocation: { items: Array<{ instrument: string; market_value: string; weight_percent: string }>; availability: { availability: string; reason?: string } };
  recent_signals: { items: Array<{ instrument: string; status: string; signal_code: string; target_weight: string; as_of_utc: string }>; availability: { availability: string; reason?: string } };
  performance_series: { items: Array<{ as_of_utc: string; equity: string; daily_return_percent: string; drawdown_percent: string }>; availability: { availability: string; reason?: string } };
  risk_safety_summary: Record<string, { value: string | null; availability: { availability: string; reason?: string } }>;
}

export function isOverviewApiResponse(value: unknown): value is OverviewApiResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<OverviewApiResponse>;
  return candidate.schema_version === "overview.v1" && typeof candidate.generated_at_utc === "string" && !!candidate.snapshot_freshness && !!candidate.portfolio_summary && !!candidate.performance_series && !!candidate.recent_signals && !!candidate.risk_safety_summary;
}
