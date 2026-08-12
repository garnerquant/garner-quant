"use client";

import { useEffect, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { ClassificationBanner } from "@/components/ClassificationBanner";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { EvidenceResponse, isEvidenceResponse } from "@/lib/evidenceApi";

type EvidenceIntegrationProps = {
  resource: string;
  version: string;
  title: string;
  emptyDescription?: string;
  variant?: "default" | "risk-health";
};

function displayControl(value: string | null | undefined, kind: "mode" | "boolean"): string {
  if (value == null) return "Unavailable";
  if (kind === "mode" && value === "monitor_only") return "Monitor only";
  if (kind === "boolean") return value === "false" ? "Disabled" : value === "true" ? "Enabled" : value;
  return value;
}

export function EvidenceIntegration({ resource, version, title, emptyDescription, variant = "default" }: EvidenceIntegrationProps) {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/${resource}`, { signal: controller.signal, cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error(`API returned ${response.status}`);
        const body: unknown = await response.json();
        if (!isEvidenceResponse(body, version)) throw new Error("Response contract was rejected");
        setData(body);
      })
      .catch(reason => {
        if (reason.name !== "AbortError") setError(String(reason));
      });
    return () => controller.abort();
  }, [resource, version]);

  if (error) return <ErrorState title={`${title} unavailable`} description={error}/>;
  if (!data) return <LoadingSkeleton/>;

  const safety = data.records.find(record => record.identity === "safety-defaults");
  const heartbeat = safety?.fields.heartbeat;
  const dataQuality = safety?.fields.data_quality;
  const healthUnavailable = !heartbeat || !dataQuality;
  const warningValue = (value: string) => value.toLowerCase().includes("unavailable") || value === "Unavailable";

  return <div className="space-y-6">
    <ClassificationBanner text={resource === "shadow-runs" ? "EVIDENCE UNAVAILABLE" : `${data.source_classification} · ${data.freshness.status}`}/>
    {data.warnings.map(warning => <p key={warning} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{warning}</p>)}
    <ChartCard title={title} subtitle={`Read-only ${version} evidence`}>
      {variant === "risk-health" ? <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[{ label: "Overall health", value: healthUnavailable ? "Evidence unavailable" : "Evidence available" }, { label: "Runtime heartbeat", value: heartbeat ?? "Unavailable" }, { label: "Dashboard status", value: healthUnavailable ? "Preview only / evidence unavailable" : "Preview only" }, { label: "Latest cycle", value: "Unavailable" }].map(item => <div key={item.label} className="rounded-xl border border-slate-700/70 bg-white/[.02] p-5"><div className="text-sm text-slate-300">{item.label}</div><div className={`mt-3 text-xl font-semibold ${warningValue(item.value) ? "text-amber" : "text-slate-100"}`}>{item.value}</div></div>)}
        </div>
        <section><h3 className="mb-3 text-lg font-semibold text-slate-100">Safety controls</h3><div className="grid gap-3 sm:grid-cols-2">{[{ label: "Runtime", value: displayControl(safety?.fields.mode, "mode") }, { label: "Paper execution", value: displayControl(safety?.fields.paper_execution_enabled, "boolean") }, { label: "Trading", value: displayControl(safety?.fields.trading_enabled, "boolean") }, { label: "Limits approved", value: safety?.fields.limits_approved === "false" ? "No" : safety?.fields.limits_approved === "true" ? "Yes" : "Unavailable" }].map(item => <div key={item.label} className="rounded-lg bg-white/[.035] px-4 py-3.5"><div className="text-[15px] text-slate-300">{item.label}</div><div className="mt-1 text-lg font-medium">{item.value}</div></div>)}</div></section>
        {!data.records.length ? <EmptyState title="No trustworthy safety evidence" description={emptyDescription ?? "The service failed closed rather than displaying preview data as real data."}/> : null}
      </div> : data.records.length ? <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr className="border-b border-slate-700 text-slate-300"><th className="p-3">Identity</th><th className="p-3">Status</th><th className="p-3">As of (UTC)</th><th className="p-3">Evidence fields</th></tr></thead><tbody>{data.records.map(record => <tr key={record.identity} className="border-b border-slate-800"><td className="p-3 font-medium">{record.identity}</td><td className="p-3">{record.status}</td><td className="p-3">{record.as_of_utc ?? "Unavailable"}</td><td className="p-3 text-sm text-slate-300">{Object.entries(record.fields).map(([key, value]) => `${key}: ${value ?? "unavailable"}`).join(" · ")}</td></tr>)}</tbody></table></div> : <EmptyState title="No trustworthy evidence" description={emptyDescription ?? "The service failed closed rather than displaying preview data as real data."}/>}
      <div className="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">{data.provenance.join(" · ")}</div>
    </ChartCard>
  </div>;
}
