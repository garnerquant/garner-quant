export interface SignalApiResponse {
  schema_version: "signals.v1";
  generated_at_utc: string;
  source_as_of_utc: string | null;
  source_classification: "local_snapshot" | "partial" | "unavailable";
  freshness: { status: "fresh" | "stale" | "unavailable"; snapshot_age_seconds: number | null };
  warnings: string[];
  source_file: string;
  items: Array<{ instrument: string; signal_code: string; status: string; target_weight: string; as_of_utc: string }>;
  availability: { availability: "available" | "partial" | "unavailable"; reason?: string };
}

export function isSignalApiResponse(value: unknown): value is SignalApiResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<SignalApiResponse>;
  return candidate.schema_version === "signals.v1" && typeof candidate.generated_at_utc === "string" && Array.isArray(candidate.items) && !!candidate.availability;
}
