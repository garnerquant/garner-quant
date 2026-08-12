"use client";

import { ReactNode, useEffect, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { DataTable, TableColumn } from "@/components/DataTable";
import { MetricCard } from "@/components/MetricCard";
import { SignalApiResponse, isSignalApiResponse } from "@/lib/signalsApi";

type State = { kind: "loading" } | { kind: "api"; data: SignalApiResponse } | { kind: "fallback" };
type Signal = SignalApiResponse["items"][number];

const timestamp = (value: string | null) => value ? `${new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(value))} UTC` : "Unavailable";
const columns: TableColumn<Signal>[] = [
  { key: "instrument", label: "Instrument", sortable: true },
  { key: "status", label: "Status", sortable: true },
  { key: "signal_code", label: "Signal", sortable: true },
  { key: "target_weight", label: "Target weight", sortable: true, className: "text-right tabular-nums", render: row => `${(Number(row.target_weight) * 100).toFixed(2)}%`, sortValue: row => Number(row.target_weight) },
];

export function SignalsIntegration({ fallback }: { fallback: ReactNode }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  useEffect(() => {
    let active = true;
    fetch("/api/signals", { cache: "no-store" })
      .then(async response => response.ok ? response.json() : Promise.reject(new Error("unavailable")))
      .then((value: unknown) => { if (active) setState(isSignalApiResponse(value) ? { kind: "api", data: value } : { kind: "fallback" }); })
      .catch(() => { if (active) setState({ kind: "fallback" }); });
    return () => { active = false; };
  }, []);

  if (state.kind === "loading") return <div className="h-96 animate-pulse rounded-xl border border-slate-700/70 bg-[#111c24]" />;
  if (state.kind === "fallback") return <div className="space-y-4"><p className="text-[15px] text-slate-300">Mock preview — the read-only signals source is unavailable. No snapshot and mock values are combined.</p>{fallback}</div>;

  const { data } = state;
  const available = data.availability.availability === "available";
  const buy = data.items.filter(item => item.signal_code === "1").length;
  const avoid = data.items.filter(item => item.signal_code === "0").length;
  return <div className="space-y-6">
    <div className="space-y-1 text-[15px] text-slate-300"><div><span className="font-medium text-slate-100">Local snapshot</span> · {data.source_classification === "local_snapshot" ? "Complete" : "Partial"} · Signals as of {timestamp(data.source_as_of_utc)}</div><div>Loaded {timestamp(data.generated_at_utc)} · Source {data.source_file}</div></div>
    {data.freshness.status === "stale" ? <p className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-[15px] text-amber">Stale snapshot — signals are older than the local freshness threshold.</p> : null}
    {!available ? <ChartCard title="Signals unavailable"><p className="text-[15px] text-slate-300">No trustworthy single-timestamp signal snapshot is available.</p><p className="mt-3 text-[15px] text-slate-300">{data.availability.reason}</p></ChartCard> : <><div className="grid gap-4 sm:grid-cols-3"><MetricCard item={{ label: "Buy / hold", value: String(buy), tone: "positive" }} /><MetricCard item={{ label: "Avoid / sell", value: String(avoid), tone: "warning" }} /><MetricCard item={{ label: "Signals", value: String(data.items.length), helper: `As of ${timestamp(data.source_as_of_utc)}`, tone: "neutral" }} /></div><ChartCard title="Strategy signals" subtitle="Read-only local snapshot"><DataTable data={data.items} columns={columns} /></ChartCard></>}
  </div>;
}
