"use client";

import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartCard } from "@/components/ChartCard";
import { EmptyState } from "@/components/EmptyState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { MetricCard } from "@/components/MetricCard";
import { StatusBadge } from "@/components/StatusBadge";
import { OverviewApiResponse, isOverviewApiResponse } from "@/lib/overviewApi";

const grid = <CartesianGrid stroke="#243640" vertical={false} />;
const axis = { stroke: "#b1c0c8", fontSize: 14, tickLine: false, axisLine: false };
const tooltip = { contentStyle: { background: "#111c24", border: "1px solid #405761", borderRadius: "8px", fontSize: 14 }, labelStyle: { color: "#e2e8f0" } };

function displayMoney(value: string | null) { return value === null ? "Unavailable" : `GBP ${Number(value).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function displayCompactMoney(value: number) { return Number.isFinite(value) ? Math.abs(value) >= 1000 ? `£${(value / 1000).toFixed(1)}k` : `£${value.toFixed(0)}` : "—"; }
function displayPercent(value: string | null) { return value === null ? "Unavailable" : `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`; }
function formatUtc(value: string | null) { return value ? `${new Date(value).toLocaleString("en-GB", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" })} UTC` : "Unavailable"; }
function chartLabel(value: string) { const date = new Date(value); return `${date.toLocaleString("en-GB", { timeZone: "UTC", month: "short" })} ’${date.getUTCFullYear().toString().slice(-2)}`; }
function performanceDomain(values: number[]): [number | "auto", number | "auto"] {
  const observed = values.filter(Number.isFinite);
  if (!observed.length) return ["auto", "auto"];
  const low = Math.min(...observed); const high = Math.max(...observed); const span = high - low;
  const padding = span > 0 ? span * 0.12 : Math.max(Math.abs(high) * 0.05, 1);
  return [low - padding, high + padding];
}
function evenlySpacedTicks(length: number) {
  if (length < 2) return [0];
  const count = Math.min(8, length);
  return Array.from({ length: count }, (_, index) => Math.round(index * (length - 1) / (count - 1))).filter((value, index, values) => values.indexOf(value) === index);
}

export function OverviewIntegration({ fallback }: { fallback: React.ReactNode }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "api"; data: OverviewApiResponse } | { kind: "fallback" }>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    fetch("/api/overview", { cache: "no-store" })
      .then(async response => ({ ok: response.ok, body: await response.json() }))
      .then(result => active && setState(result.ok && isOverviewApiResponse(result.body) ? { kind: "api", data: result.body } : { kind: "fallback" }))
      .catch(() => active && setState({ kind: "fallback" }));
    return () => { active = false; };
  }, []);

  if (state.kind === "loading") return <LoadingSkeleton />;
  if (state.kind === "fallback") return <div className="space-y-4"><p className="text-[15px] text-slate-300"><StatusBadge label="Mock fallback" tone="warning" /> <span className="ml-2">The local snapshot is unavailable; no snapshot and mock values are combined.</span></p>{fallback}</div>;

  const { data } = state;
  const points = data.performance_series.items.map((item, index) => ({ index, sourceAsOf: item.as_of_utc, portfolio: Number(item.equity) }));
  const domain = performanceDomain(points.map(point => point.portfolio));
  const xTicks = evenlySpacedTicks(points.length);
  const allocationMessage = data.allocation.availability.reason?.includes("inconsistent timestamps") ? "Holdings have inconsistent timestamps" : "Allocation is unavailable from this snapshot.";
  const safetyItems = [["Runtime", data.risk_safety_summary.mode], ["Paper execution", data.risk_safety_summary.paper_execution_enabled], ["Trading", data.risk_safety_summary.trading_enabled], ["Limits approved", data.risk_safety_summary.limits_approved]] as const;
  const ageDays = data.snapshot_freshness.snapshot_age_seconds === null ? null : Math.floor(data.snapshot_freshness.snapshot_age_seconds / 86400);

  return <div className="space-y-6"><div className="space-y-2 text-[15px] text-slate-300"><p><StatusBadge label="Local snapshot" tone="neutral" /> <span className="ml-2">· {data.source_classification === "partial" ? "Partial" : "Local snapshot"}</span></p><p>Portfolio data as of {formatUtc(data.source_as_of_utc)}</p><p>Loaded {formatUtc(data.generated_at_utc)}</p>{data.snapshot_freshness.status === "stale" && ageDays !== null ? <p className="text-amber">Stale snapshot — portfolio data is {ageDays} days old</p> : null}</div><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[
    { label: "Portfolio Value", value: displayMoney(data.portfolio_summary.portfolio_value), tone: "neutral" as const },
    { label: "Latest recorded change", value: displayPercent(data.portfolio_summary.daily_change_percent), helper: formatUtc(data.portfolio_summary.latest_recorded_change_as_of_utc), tone: "positive" as const },
    { label: "Total Return", value: displayPercent(data.portfolio_summary.total_return_percent), tone: "positive" as const },
    { label: "Cash", value: displayMoney(data.portfolio_summary.cash), tone: "neutral" as const },
  ].map(item => <MetricCard key={item.label} item={item} />)}</div><div className="grid gap-5 xl:grid-cols-[minmax(0,1.8fr)_minmax(300px,.8fr)]"><ChartCard title="Portfolio performance" subtitle="Local snapshot · benchmark unavailable from mounted sources"><div className="h-[390px]">{points.length ? <ResponsiveContainer><LineChart data={points}>{grid}<XAxis dataKey="index" type="number" domain={[0, Math.max(points.length - 1, 1)]} ticks={xTicks} tickFormatter={value => chartLabel(points[Number(value)]?.sourceAsOf ?? "")} {...axis}/><YAxis {...axis} width={64} domain={domain} tickFormatter={displayCompactMoney}/><Tooltip {...tooltip} labelFormatter={value => formatUtc(points[Number(value)]?.sourceAsOf ?? null)} formatter={(value: number | string) => [displayMoney(String(value)), "Portfolio"]}/><Legend wrapperStyle={{ fontSize: 14 }}/><Line type="monotone" dataKey="portfolio" name="Portfolio" stroke="#72c59a" strokeWidth={3} dot={false}/></LineChart></ResponsiveContainer> : <EmptyState title="Performance unavailable" description="The local portfolio series could not be validated." />}</div></ChartCard><div className="space-y-5"><ChartCard title="Allocation"><EmptyState title="Allocation unavailable" description={allocationMessage} /></ChartCard><ChartCard title="Risk summary"><div className="space-y-3">{safetyItems.map(([label, item]) => <div key={label} className="flex items-center justify-between text-[15px]"><span className="text-slate-300">{label}</span><span className="text-slate-100">{item.value ?? "Unavailable"}</span></div>)}</div></ChartCard></div></div><div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]"><ChartCard title="Recent signals"><div className="divide-y divide-slate-700/60">{data.recent_signals.items.length ? data.recent_signals.items.map(item => <div key={item.instrument} className="flex items-center justify-between py-3.5"><div><b className="text-base">{item.instrument}</b><p className="text-[15px] text-slate-300">Target weight {Number(item.target_weight).toFixed(2)}</p></div><StatusBadge label={item.status} tone="neutral" /></div>) : <EmptyState title="Signals unavailable" description={data.recent_signals.availability.reason || "No validated signal snapshot is available."} />}</div></ChartCard><ChartCard title="Current holdings"><EmptyState title="Holdings unavailable" description={data.holdings_summary.availability.reason || "No internally consistent holdings snapshot is available."} /></ChartCard></div>{data.warnings.length ? <p className="text-[14px] text-slate-400">Snapshot warnings: {data.warnings.join(" · ")}</p> : null}</div>;
}
