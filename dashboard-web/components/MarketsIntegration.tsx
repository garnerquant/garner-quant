"use client";

import { useEffect, useMemo, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { ClassificationBanner } from "@/components/ClassificationBanner";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { EvidenceResponse, EvidenceRecord, isEvidenceResponse } from "@/lib/evidenceApi";

const label = (value: string | null | undefined) => value ? value.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase()) : "Unavailable";
const timestamp = (value: string | null) => value ? `${new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(value))} UTC` : "Unavailable";
const tone = (status: string): "positive" | "warning" | "negative" | "neutral" => status === "available" ? "positive" : status === "unavailable" ? "negative" : "warning";

function MarketRecord({ record }: { record: EvidenceRecord }) {
  const f = record.fields;
  return <article className="rounded-xl border border-slate-700/70 bg-white/[.02] p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold text-slate-100">{f.name ?? record.identity}</h3><p className="mt-1 text-sm text-slate-400">{record.identity} · {f.asset_class ?? "Asset class unavailable"} · {f.exchange ?? "Exchange unavailable"}</p></div><StatusBadge label={label(record.status)} tone={tone(record.status)} /></div>
    <div className="mt-5 grid gap-4 sm:grid-cols-2"><div><p className="text-sm text-slate-400">Latest observed price</p><p className="mt-1 text-2xl font-semibold tabular-nums">{f.price ? `${f.currency ?? ""} ${f.price}` : "Unavailable"}</p></div><div><p className="text-sm text-slate-400">Market status</p><p className="mt-1 text-slate-100">{label(f.market_status)}</p></div></div>
    <dl className="mt-5 grid gap-3 border-t border-slate-700/70 pt-4 text-sm sm:grid-cols-2"><div><dt className="text-slate-400">Provider</dt><dd className="mt-1 text-slate-200">{f.provider ?? "Unavailable"}</dd></div><div><dt className="text-slate-400">Observed at (UTC)</dt><dd className="mt-1 text-slate-200">{timestamp(record.as_of_utc)}</dd></div><div><dt className="text-slate-400">Price unit</dt><dd className="mt-1 text-slate-200">{f.price_unit ?? "Unavailable"}</dd></div><div><dt className="text-slate-400">Freshness threshold</dt><dd className="mt-1 text-slate-200">{f.freshness_threshold_seconds ? `${Math.round(Number(f.freshness_threshold_seconds) / 60)} minutes` : "Unavailable"}</dd></div></dl>
  </article>;
}

export function MarketsIntegration() {
  const [data, setData] = useState<EvidenceResponse | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { const controller = new AbortController(); fetch("/api/markets", { cache: "no-store", signal: controller.signal }).then(async r => { if (!r.ok) throw new Error(`API returned ${r.status}`); const body: unknown = await r.json(); if (!isEvidenceResponse(body, "markets.v1")) throw new Error("Response contract was rejected"); setData(body); }).catch(e => { if (e.name !== "AbortError") setError(String(e)); }); return () => controller.abort(); }, []);
  const groups = useMemo(() => { if (!data) return []; const result = new Map<string, EvidenceRecord[]>(); data.records.forEach(record => { const key = `${record.fields.asset_class ?? "Unknown asset class"} · ${record.fields.exchange ?? "Unknown exchange"}`; result.set(key, [...(result.get(key) ?? []), record]); }); return [...result.entries()]; }, [data]);
  if (error) return <ErrorState title="Markets unavailable" description={error}/>;
  if (!data) return <LoadingSkeleton/>;
  return <div className="space-y-6"><ClassificationBanner text={`READ-ONLY MARKET DATA · ${data.source_classification} · ${data.freshness.status}`}/>{data.warnings.map(w => <p key={w} className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-amber">{w}</p>)}<ChartCard title="Supported markets" subtitle="Observed market data only; no signals or execution state is inferred.">{!data.records.length ? <EmptyState title="No trustworthy market data" description="The API failed closed because a validated instrument or timestamped market snapshot is unavailable."/> : <div className="space-y-7">{groups.map(([group, records]) => <section key={group}><h3 className="mb-3 text-lg font-semibold text-slate-100">{group}</h3><div className="grid gap-4 lg:grid-cols-2">{records.map(record => <MarketRecord key={record.identity} record={record}/>)}</div></section>)}</div>}<div className="mt-6 border-t border-slate-700 pt-4 text-sm text-slate-400"><p>{data.provenance.join(" ")}</p><p className="mt-2">Generated {timestamp(data.generated_at_utc)} · Signals are not orders; execution remains monitor only and unavailable here.</p></div></ChartCard></div>;
}
