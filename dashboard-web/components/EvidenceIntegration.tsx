"use client";

import { useEffect, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { ClassificationBanner } from "@/components/ClassificationBanner";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { EvidenceResponse, EvidenceRecord, isEvidenceResponse } from "@/lib/evidenceApi";

type EvidenceVariant = "default" | "risk-health" | "audit" | "research" | "shadow-runs" | "signals";

type EvidenceIntegrationProps = {
  resource: string;
  version: string;
  title: string;
  emptyDescription?: string;
  variant?: EvidenceVariant;
};

const researchFields = [
  ["dataset", "Dataset snapshot"],
  ["schema_version", "Schema version"],
  ["content_hash", "Content hash"],
  ["strategy", "Strategy"],
  ["parameters", "Parameters"],
  ["execution_model", "Execution model"],
  ["cost_model", "Cost model"],
  ["information_cutoff", "Information cutoff"],
  ["code_version", "Code version"],
] as const;

function displayControl(value: string | null | undefined, kind: "mode" | "boolean"): string {
  if (value == null) return "Unavailable";
  if (kind === "mode" && value === "monitor_only") return "Monitor only";
  if (kind === "boolean") return value === "false" ? "Disabled" : value === "true" ? "Enabled" : value;
  return value;
}

function humanize(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  return value.replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase());
}

function shortValue(value: string, limit = 34): string {
  return value.length > limit ? `${value.slice(0, limit - 3)}...` : value;
}

function shortRunId(value: string): string {
  if (value.length <= 24) return value;
  const separator = value.indexOf("-");
  if (separator > 0) return `${value.slice(0, separator + 4)}...`;
  return shortValue(value, 24);
}

function valueFor(record: EvidenceRecord, key: string): string {
  return record.fields[key] ?? "Unavailable";
}

function verificationTone(status: string): "positive" | "negative" | "warning" | "neutral" {
  if (status === "verified" || status === "info" || status === "observed") return "positive";
  if (status === "high" || status === "critical") return "negative";
  if (status === "unavailable" || status === "mismatch") return "negative";
  if (status === "drift" || status === "partial") return "warning";
  return "neutral";
}

function ExpandableDetails({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return <div className="mt-3 border-t border-slate-700/70 pt-3">
    <button type="button" onClick={() => setOpen(current => !current)} className="flex w-full items-center justify-between text-left text-sm font-medium text-slate-300 hover:text-slate-100">
      {title}<span aria-hidden="true">{open ? "-" : "+"}</span>
    </button>
    {open ? <div className="mt-3">{children}</div> : null}
  </div>;
}

function FieldRows({ record, fields, full = false }: { record: EvidenceRecord; fields: readonly (readonly [string, string])[]; full?: boolean }) {
  return <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
    {fields.map(([key, label]) => {
      const value = valueFor(record, key);
      return <div key={key} className="min-w-0">
        <dt className="text-sm text-slate-400">{label}</dt>
        <dd title={value === "Unavailable" ? undefined : value} className={`mt-1 text-sm text-slate-100 ${full ? "break-all" : "truncate"}`}>{value === "Unavailable" ? <span className="text-slate-500">Unavailable</span> : full ? value : shortValue(value)}</dd>
      </div>;
    })}
  </dl>;
}

function EvidenceFieldRows({ record }: { record: EvidenceRecord }) {
  return <dl className="space-y-3">
    {Object.entries(record.fields).map(([key, value]) => <div key={key}>
      <dt className="text-sm text-slate-400">{humanize(key)}</dt>
      <dd className="mt-1 break-all text-xs text-slate-200">{value ?? "Unavailable"}</dd>
    </div>)}
  </dl>;
}

function ResearchEvidence({ data, emptyDescription }: { data: EvidenceResponse; emptyDescription?: string }) {
  const [showAll, setShowAll] = useState(false);
  if (!data.records.length) return <EmptyState title="No trustworthy research evidence" description={emptyDescription ?? "The service failed closed rather than displaying preview data as real data."}/>;
  const records = showAll ? data.records : data.records.slice(0, 3);
  return <div className="space-y-4">
    {records.map(record => <article key={record.identity} className="rounded-xl border border-slate-700/70 bg-white/[.02] px-5 py-4">
      <div className="grid gap-4 sm:grid-cols-[1.3fr_1fr_1.5fr_1fr] sm:items-center">
        <div className="min-w-0"><p className="text-sm text-slate-400">Run</p><h3 className="mt-1 truncate font-semibold text-slate-100">{shortRunId(record.identity)}</h3></div>
        <div><p className="text-sm text-slate-400">Status</p><div className="mt-1"><StatusBadge label={humanize(record.status)} tone={verificationTone(record.status)}/></div></div>
        <div className="min-w-0"><p className="text-sm text-slate-400">Dataset</p><p className="mt-1 truncate text-sm text-slate-100">{shortValue(valueFor(record, "dataset"), 42)}</p></div>
        <div><p className="text-sm text-slate-400">Reproducibility</p><p className={`mt-1 text-sm ${record.status === "verified" ? "text-mint" : "text-amber"}`}>{record.status === "unavailable" ? "Unavailable" : record.status === "verified" ? "Complete" : "Incomplete"}</p></div>
      </div>
      <ExpandableDetails title="Details">
        <dl className="mb-4 grid gap-3 sm:grid-cols-2">
          <div><dt className="text-sm text-slate-400">Full run ID</dt><dd className="mt-1 break-all font-mono text-sm text-slate-200">{record.identity}</dd></div>
          <div><dt className="text-sm text-slate-400">As of (UTC)</dt><dd className="mt-1 text-sm text-slate-200">{record.as_of_utc ?? "Unavailable"}</dd></div>
        </dl>
        <FieldRows record={record} fields={researchFields} full/>
      </ExpandableDetails>
    </article>)}
    {data.records.length > 3 ? <button type="button" onClick={() => setShowAll(current => !current)} className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:border-slate-400">{showAll ? "Show fewer runs" : "View all runs"}</button> : null}
  </div>;
}

function AuditEvidence({ data }: { data: EvidenceResponse }) {
  const [showAll, setShowAll] = useState(false);
  const records = showAll ? data.records : data.records.slice(0, 5);
  return <div className="space-y-4">
    <p className="max-w-2xl text-base leading-7 text-slate-200">Some evidence is verified, but freshness or mounted-artifact verification is incomplete.</p>
    {data.records.length ? <div className="overflow-x-auto rounded-xl border border-slate-700/70">
      <table className="min-w-[680px] w-full table-fixed text-left">
        <thead><tr className="border-b border-slate-700 text-sm text-slate-400"><th className="w-[34%] p-4">Artifact</th><th className="w-[22%] p-4">Status</th><th className="w-[24%] p-4">Verification</th><th className="w-[20%] p-4">Freshness</th></tr></thead>
        <tbody>{records.map(record => {
          const freshness = record.as_of_utc ? humanize(data.freshness.status) : "Unavailable";
          const verification = record.status === "verified" ? "Checks passed" : record.status === "partial" || record.status === "drift" ? "Checks incomplete" : record.status === "unavailable" ? "Not available" : "Needs review";
          return <tr key={record.identity} className="border-b border-slate-800 align-top last:border-b-0">
            <td className="p-4"><span className="block truncate font-medium text-slate-100">{shortValue(record.identity, 44)}</span><ExpandableDetails title="Details"><div className="space-y-4"><div><p className="text-sm text-slate-400">Full artifact path</p><p className="mt-1 break-all font-mono text-xs text-slate-200">{record.identity}</p></div><EvidenceFieldRows record={record}/><div><p className="text-sm text-slate-400">Evidence status</p><p className="mt-1 break-all text-xs text-slate-200">{record.status}</p></div></div></ExpandableDetails></td>
            <td className="p-4"><StatusBadge label={humanize(record.status)} tone={verificationTone(record.status)}/></td>
            <td className="p-4 text-sm text-slate-200">{verification}</td>
            <td className="p-4 text-sm"><span className={freshness === "Unavailable" ? "text-amber" : "text-slate-200"}>{freshness}</span></td>
          </tr>;
        })}</tbody>
      </table>
    </div> : <EmptyState title="No trustworthy audit evidence" description="The service failed closed rather than displaying preview data as real data."/>}
    {data.records.length > 5 ? <button type="button" onClick={() => setShowAll(current => !current)} className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:border-slate-400">{showAll ? "Show fewer records" : "View all evidence"}</button> : null}
  </div>;
}

function ShadowRunsEvidence({ data }: { data: EvidenceResponse }) {
  return <div className="space-y-6"><p className="max-w-3xl text-sm leading-6 text-slate-300">Observed evaluations, risk decisions, eligible actions, and actual execution are separate evidence domains. Eligibility never implies execution.</p>{data.records.length ? <div className="grid gap-4 lg:grid-cols-2">{data.records.map(record => <article key={record.identity} className="rounded-xl border border-slate-700/70 bg-white/[.02] p-4"><div className="flex items-start justify-between gap-3"><h3 className="font-medium text-slate-100">{record.fields.instrument ?? record.identity}</h3><StatusBadge label={humanize(record.status)} tone={verificationTone(record.status)}/></div><dl className="mt-4 grid gap-3 sm:grid-cols-2">{[["Evaluation (UTC)", record.fields.evaluation_timestamp_utc ?? record.as_of_utc], ["Strategy", record.fields.strategy], ["Strategy version", record.fields.strategy_version], ["Configuration version", record.fields.configuration_version], ["Bar identity", record.fields.bar_identity], ["Signal / observed result", record.fields.signal_result], ["Risk decision", record.fields.risk_decision], ["Eligible action", record.fields.execution_eligibility], ["Execution status", record.fields.execution_status], ["Retryable state", record.fields.retryable_state], ["Duplicate-bar state", record.fields.duplicate_bar_state], ["Source / timestamp", `${record.fields.source_path ?? "Unavailable"} | ${record.fields.source_timestamp_utc ?? "no timestamp"}`]].map(([label, value]) => <div key={label}><dt className="text-xs text-slate-400">{label}</dt><dd className="mt-1 break-words text-sm text-slate-200">{value ?? "Evidence unavailable"}</dd></div>)}</dl><p className="mt-4 border-t border-slate-700/70 pt-3 text-xs text-slate-400">Definition: {record.fields.definition ?? "Unavailable"}</p><p className="mt-2 text-xs text-amber">Operator action: {record.fields.operator_action ?? "Review unavailable evidence before relying on this record."}</p></article>)}</div> : <EmptyState title="Shadow-run evidence unavailable" description="No verified run records are displayed. Operator action: mount and validate the runtime decision artifact before relying on this page."/>}</div>;
}

function SignalsEvidence({ data }: { data: EvidenceResponse }) {
  return <div className="space-y-6"><p className="text-sm leading-6 text-slate-300">Observed market evidence, derived signal, risk decision, eligibility, and execution are separate. A signal is not an order or trade.</p>{data.records.length ? <div className="overflow-x-auto rounded-xl border border-slate-700/70"><table className="min-w-[980px] w-full text-left"><thead><tr className="border-b border-slate-700 text-sm text-slate-400"><th className="p-4">Instrument</th><th className="p-4">Signal</th><th className="p-4">Risk / eligibility</th><th className="p-4">Execution</th><th className="p-4">Evidence</th></tr></thead><tbody>{data.records.map(record => <tr key={record.identity} className="border-b border-slate-800 align-top"><td className="p-4 font-medium text-slate-100">{record.identity}<p className="mt-2 text-xs text-slate-400">Source: {record.fields.source_path ?? "Unavailable"}<br/>Timestamp: {record.fields.source_timestamp_utc ?? "No timestamp"}</p></td><td className="p-4 text-sm text-slate-200">{record.fields.signal_code ?? "Unavailable"}<p className="mt-2 text-xs text-slate-400">{record.fields.signal_status ?? "Unavailable"}</p></td><td className="p-4 text-sm text-slate-200">Risk: {record.fields.risk_decision ?? "Unavailable"}<br/>Eligibility: {record.fields.execution_eligibility ?? "Unavailable"}<p className="mt-2 text-xs text-amber">Reason: {record.fields.risk_reason ?? "Unavailable"}</p></td><td className="p-4 text-sm text-amber">{record.fields.execution_status ?? "Unavailable"}<p className="mt-2 text-xs text-slate-400">Retryable: {record.fields.retryable_state ?? "Unavailable"}<br/>Duplicate: {record.fields.duplicate_state ?? "Unavailable"}</p></td><td className="p-4 text-xs text-slate-300">Severity: {record.fields.severity ?? record.status}<br/>Definition: {record.fields.definition ?? "Unavailable"}<p className="mt-2 text-amber">Action: {record.fields.operator_action ?? "Review unavailable evidence."}</p></td></tr>)}</tbody></table></div> : <EmptyState title="Signal evidence unavailable" description="No trustworthy candidates are displayed. Operator action: mount and validate the signal snapshot and matching market/risk evidence."/>}</div>;
}

function RiskHealthEvidence({ data }: { data: EvidenceResponse }) {
  const control = data.records.find(record => record.identity === "safety-defaults");
  const rows = data.records.filter(record => record.identity !== "safety-defaults");
  const controls = [["Monitor-only mode", control?.fields.mode ? displayControl(control.fields.mode, "mode") : "Unavailable"], ["Paper execution", control?.fields.paper_execution_enabled ? displayControl(control.fields.paper_execution_enabled, "boolean") : "Unavailable"], ["Trading enabled", control?.fields.trading_enabled ? displayControl(control.fields.trading_enabled, "boolean") : "Unavailable"], ["Limits approved", control?.fields.limits_approved === "false" ? "No" : control?.fields.limits_approved === "true" ? "Yes" : "Unavailable"]];
  return <div className="space-y-6"><section><h3 className="mb-3 text-lg font-semibold text-slate-100">Safety and execution controls</h3><div className="grid gap-3 sm:grid-cols-2">{controls.map(([name, value]) => <div key={name} className="rounded-lg border border-slate-700/70 bg-white/[.035] px-4 py-3.5"><div className="text-sm text-slate-400">{name}</div><div className="mt-1 text-lg font-medium">{value}</div><dl className="mt-3 space-y-1 text-xs"><div><dt className="inline text-slate-500">Source: </dt><dd className="inline text-slate-300">{control?.fields.source_file ?? "Unavailable"}</dd></div><div><dt className="inline text-slate-500">Timestamp: </dt><dd className="inline text-slate-300">{control?.as_of_utc ?? "Unavailable"}</dd></div><div><dt className="inline text-slate-500">Severity: </dt><dd className="inline text-slate-300">{control?.status ?? "Unavailable"}</dd></div></dl><p className="mt-3 text-xs text-slate-400">Definition: {control?.fields.definition ?? "Unavailable"}</p><p className="mt-2 text-xs text-amber">Operator action: {control?.fields.operator_action ?? "Review evidence before relying on this value."}</p></div>)}</div></section><section><h3 className="mb-3 text-lg font-semibold text-slate-100">Runtime and evidence checks</h3>{rows.length ? <div className="grid gap-4 lg:grid-cols-2">{rows.map(record => <article key={record.identity} className="rounded-xl border border-slate-700/70 bg-white/[.02] p-4"><div className="flex items-start justify-between gap-3"><h4 className="font-medium text-slate-100">{humanize(record.identity)}</h4><StatusBadge label={humanize(record.status)} tone={verificationTone(record.status)}/></div><dl className="mt-4 grid gap-3 sm:grid-cols-2"><div><dt className="text-xs text-slate-400">Recorded value</dt><dd className="mt-1 text-sm text-slate-200">{record.fields.value ?? "Unavailable"}</dd></div><div><dt className="text-xs text-slate-400">As of (UTC)</dt><dd className="mt-1 text-sm text-slate-200">{record.as_of_utc ?? "Unavailable"}</dd></div><div><dt className="text-xs text-slate-400">Severity</dt><dd className="mt-1 text-sm text-slate-200">{record.fields.severity ?? record.status}</dd></div><div><dt className="text-xs text-slate-400">Source</dt><dd className="mt-1 break-all text-sm text-slate-200">{record.fields.source_file ?? "Unavailable"}</dd></div></dl><p className="mt-4 border-t border-slate-700/70 pt-3 text-sm text-slate-300"><span className="text-slate-400">Definition:</span> {record.fields.definition ?? "Unavailable"}</p><p className="mt-2 text-sm text-amber"><span className="text-slate-400">Operator action:</span> {record.fields.operator_action ?? "Review evidence before relying on this value."}</p></article>)}</div> : <EmptyState title="Risk evidence unavailable" description="No validated runtime evidence was returned. Operator action: mount the read-only runtime artifacts and review them before relying on this page."/>}</section></div>;
}

function AuditReviewEvidence({ data }: { data: EvidenceResponse }) {
  const artifacts = data.records.filter(record => record.fields.classification !== "audit_result");
  const domains = data.records.filter(record => record.fields.classification === "audit_result");
  const artifactRows = artifacts.slice(0, 10);
  return <div className="space-y-6"><section><h3 className="mb-3 text-lg font-semibold text-slate-100">Audit domain outcomes</h3>{domains.length ? <div className="grid gap-4 lg:grid-cols-2">{domains.map(record => <article key={record.identity} className="rounded-xl border border-slate-700/70 bg-white/[.02] p-4"><div className="flex items-start justify-between gap-3"><h4 className="font-medium text-slate-100">{humanize(record.identity)}</h4><StatusBadge label="Unavailable" tone="negative"/></div><dl className="mt-4 grid gap-3 sm:grid-cols-2"><div><dt className="text-xs text-slate-400">Source path</dt><dd className="mt-1 text-sm text-slate-200">{record.fields.source_path ?? "Unavailable"}</dd></div><div><dt className="text-xs text-slate-400">Timestamp</dt><dd className="mt-1 text-sm text-slate-200">{record.as_of_utc ?? "Unavailable"}</dd></div><div><dt className="text-xs text-slate-400">Severity</dt><dd className="mt-1 text-sm text-amber">{record.fields.severity ?? "Unavailable"}</dd></div></dl><p className="mt-4 border-t border-slate-700/70 pt-3 text-sm text-slate-300"><span className="text-slate-400">Definition:</span> {record.fields.definition ?? "Unavailable"}</p><p className="mt-2 text-sm text-amber"><span className="text-slate-400">Operator action:</span> {record.fields.operator_action ?? "Review unavailable evidence."}</p></article>)}</div> : <EmptyState title="Audit domains unavailable" description="No validated domain results were returned."/>}</section><section><h3 className="mb-3 text-lg font-semibold text-slate-100">Artifact evidence</h3>{artifactRows.length ? <div className="overflow-x-auto rounded-xl border border-slate-700/70"><table className="min-w-[860px] w-full text-left"><thead><tr className="border-b border-slate-700 text-sm text-slate-400"><th className="p-4">Source path</th><th className="p-4">Classification / ownership</th><th className="p-4">Mutability</th><th className="p-4">Hash observation</th><th className="p-4">Timestamp</th></tr></thead><tbody>{artifactRows.map(record => <tr key={record.identity} className="border-b border-slate-800 align-top"><td className="p-4"><span className="break-all text-sm text-slate-100">{record.fields.source_path ?? record.identity}</span><p className="mt-2 text-xs text-slate-400">Action: {record.fields.operator_action ?? "Unavailable"}</p></td><td className="p-4 text-sm text-slate-200">{record.fields.classification ?? "Unavailable"}<br/><span className="text-slate-400">{record.fields.ownership ?? "Unavailable"}</span></td><td className="p-4 text-sm text-slate-200">{record.fields.mutability ?? "Unavailable"}</td><td className="p-4"><StatusBadge label={record.status === "verified" ? "Hash matches baseline" : humanize(record.status)} tone={verificationTone(record.status)}/><p className="mt-2 text-xs text-slate-400">{record.fields.definition ?? "Unavailable"}</p></td><td className="p-4 text-sm text-slate-200">{record.as_of_utc ?? "Unavailable"}</td></tr>)}</tbody></table></div> : <EmptyState title="No artifact evidence" description="The manifest is unavailable or produced no safe records."/>}{artifacts.length > 10 ? <p className="mt-3 text-sm text-slate-400">Showing 10 of {artifacts.length} artifacts; all records remain available through the read-only API.</p> : null}</section></div>;
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
      .catch(reason => { if (reason.name !== "AbortError") setError(String(reason)); });
    return () => controller.abort();
  }, [resource, version]);

  if (error) return <ErrorState title={`${title} unavailable`} description={error}/>;
  if (!data) return <LoadingSkeleton/>;
  if (variant === "audit") return <div className="space-y-6"><ClassificationBanner text={`${data.source_classification} | ${data.freshness.status}`}/>{data.warnings.map(warning => <p key={warning} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{warning}</p>)}<ChartCard title={title} subtitle="Read-only audit evidence; observations and operator interpretation remain separate"><AuditReviewEvidence data={data}/><div className="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">{data.provenance.join(" | ")}</div></ChartCard></div>;
  if (variant === "risk-health") return <div className="space-y-6"><ClassificationBanner text={`${data.source_classification} | ${data.freshness.status}`}/>{data.warnings.map(warning => <p key={warning} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{warning}</p>)}<ChartCard title={title} subtitle="Read-only risk and runtime evidence"><RiskHealthEvidence data={data}/><div className="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">{data.provenance.join(" | ")}</div></ChartCard></div>;
  if (variant === "shadow-runs") return <div className="space-y-6"><ClassificationBanner text={`${data.source_classification} | ${data.freshness.status}`}/>{data.warnings.map(warning => <p key={warning} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{warning}</p>)}<ChartCard title={title} subtitle="Read-only verified shadow evaluation evidence"><ShadowRunsEvidence data={data}/><div className="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">{data.provenance.join(" | ")}</div></ChartCard></div>;
  if (variant === "signals" || resource === "signals") return <div className="space-y-6"><ClassificationBanner text={`${data.source_classification} | ${data.freshness.status}`}/>{data.warnings.map(warning => <p key={warning} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{warning}</p>)}<ChartCard title={title} subtitle="Read-only evidence-backed signal candidates"><SignalsEvidence data={data}/><div className="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">{data.provenance.join(" | ")}</div></ChartCard></div>;

  const safety = data.records.find(record => record.identity === "safety-defaults");
  const heartbeat = safety?.fields.heartbeat;
  const dataQuality = safety?.fields.data_quality;
  const healthUnavailable = !heartbeat || !dataQuality;
  const warningValue = (value: string) => value.toLowerCase().includes("unavailable") || value === "Unavailable";

  return <div className="space-y-6">
    <ClassificationBanner text={resource === "shadow-runs" ? "EVIDENCE UNAVAILABLE" : `${data.source_classification} | ${data.freshness.status}`}/>
    {data.warnings.map(warning => <p key={warning} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{warning}</p>)}
    <ChartCard title={title} subtitle={`Read-only ${version} evidence`}>
      {variant === "research" ? <ResearchEvidence data={data} emptyDescription={emptyDescription}/> : (variant as string) === "audit" ? <AuditEvidence data={data}/> : (variant as string) === "risk-health" ? <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[{ label: "Overall health", value: healthUnavailable ? "Evidence unavailable" : "Evidence available" }, { label: "Runtime heartbeat", value: heartbeat ?? "Unavailable" }, { label: "Dashboard status", value: healthUnavailable ? "Preview only / evidence unavailable" : "Preview only" }, { label: "Latest cycle", value: "Unavailable" }].map(item => <div key={item.label} className="rounded-xl border border-slate-700/70 bg-white/[.02] p-5"><div className="text-sm text-slate-300">{item.label}</div><div className={`mt-3 text-xl font-semibold ${warningValue(item.value) ? "text-amber" : "text-slate-100"}`}>{item.value}</div></div>)}</div>
        <section><h3 className="mb-3 text-lg font-semibold text-slate-100">Safety controls</h3><div className="grid gap-3 sm:grid-cols-2">{[{ label: "Runtime", value: displayControl(safety?.fields.mode, "mode") }, { label: "Paper execution", value: displayControl(safety?.fields.paper_execution_enabled, "boolean") }, { label: "Trading", value: displayControl(safety?.fields.trading_enabled, "boolean") }, { label: "Limits approved", value: safety?.fields.limits_approved === "false" ? "No" : safety?.fields.limits_approved === "true" ? "Yes" : "Unavailable" }].map(item => <div key={item.label} className="rounded-lg bg-white/[.035] px-4 py-3.5"><div className="text-[15px] text-slate-300">{item.label}</div><div className="mt-1 text-lg font-medium">{item.value}</div></div>)}</div></section>
        {!data.records.length ? <EmptyState title="No trustworthy safety evidence" description={emptyDescription ?? "The service failed closed rather than displaying preview data as real data."}/> : null}
      </div> : data.records.length ? <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr className="border-b border-slate-700 text-slate-300"><th className="p-3">Identity</th><th className="p-3">Status</th><th className="p-3">As of (UTC)</th><th className="p-3">Evidence fields</th></tr></thead><tbody>{data.records.map(record => <tr key={record.identity} className="border-b border-slate-800"><td className="p-3 font-medium">{record.identity}</td><td className="p-3">{record.status}</td><td className="p-3">{record.as_of_utc ?? "Unavailable"}</td><td className="p-3 text-sm text-slate-300">{Object.entries(record.fields).map(([key, value]) => `${key}: ${value ?? "unavailable"}`).join(" | ")}</td></tr>)}</tbody></table></div> : <EmptyState title="No trustworthy evidence" description={emptyDescription ?? "The service failed closed rather than displaying preview data as real data."}/>}
      <div className="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">{data.provenance.join(" | ")}</div>
    </ChartCard>
  </div>;
}
