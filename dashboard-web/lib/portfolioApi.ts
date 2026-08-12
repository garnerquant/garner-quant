export interface Availability {
  availability: "available" | "partial" | "unavailable";
  reason?: string;
}

export interface PortfolioApiResponse {
  schema_version: "portfolio.v1";
  generated_at_utc: string;
  source_as_of_utc: string | null;
  source_classification: "local_snapshot" | "partial" | "unavailable";
  freshness: { status: "fresh" | "stale" | "unavailable"; snapshot_age_seconds: number | null };
  warnings: string[];
  portfolio_summary: {
    portfolio_value: string | null;
    as_of_utc: string | null;
    holdings_market_value: string | null;
    holdings_as_of_utc: string | null;
    reconciliation: Availability;
    availability: Availability;
  };
  holdings: { as_of_utc: string | null; items: Array<{ instrument: string; quantity: string; entry_price: string; current_price: string; market_value: string; unrealised_pnl: string; unrealised_pnl_percent: string }>; availability: Availability };
  allocation: { items: Array<{ instrument: string; market_value: string; weight_percent: string }>; availability: Availability };
  cash: { value: string | null; availability: Availability };
  section_availability: Record<string, Availability>;
}

export function isPortfolioApiResponse(value: unknown): value is PortfolioApiResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<PortfolioApiResponse>;
  return candidate.schema_version === "portfolio.v1" && typeof candidate.generated_at_utc === "string" && !!candidate.portfolio_summary && !!candidate.holdings && !!candidate.allocation && !!candidate.cash;
}
