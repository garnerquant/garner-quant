export interface EvidenceRecord { identity: string; as_of_utc: string | null; status: string; fields: Record<string, string | null> }
export interface EvidenceResponse { schema_version: string; generated_at_utc: string; source_as_of_utc: string | null; source_classification: "local_snapshot" | "partial" | "unavailable"; freshness: { status: "fresh" | "stale" | "unavailable" }; provenance: string[]; warnings: string[]; records: EvidenceRecord[] }

export function isEvidenceResponse(value: unknown, version: string): value is EvidenceResponse {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<EvidenceResponse>;
  return item.schema_version === version && Array.isArray(item.records) && Array.isArray(item.warnings) && Array.isArray(item.provenance);
}
