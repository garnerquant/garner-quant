"use client";

import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { ChartCard } from "@/components/ChartCard";
import { DataTable, TableColumn } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MetricCard } from "@/components/MetricCard";
import { PortfolioApiResponse, isPortfolioApiResponse } from "@/lib/portfolioApi";

type SourceState = { kind: "loading" } | { kind: "api"; data: PortfolioApiResponse } | { kind: "error" };
type Position = PortfolioApiResponse["holdings"]["items"][number];
type TablePosition = Position & { allocation: number | null; cost_basis: number };

const colours = ["#5fb8b1", "#72c59a", "#cda96b", "#8496a3", "#6689a8"];
const money = (value: string) => `GBP ${Number(value).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const timestamp = (value: string | null) => value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(value)) + " UTC" : "Unavailable";
const costBasis = (row: Position) => Number(row.quantity) * Number(row.entry_price);

const positionColumns: TableColumn<TablePosition>[] = [
  { key: "instrument", label: "Instrument", sortable: true },
  { key: "quantity", label: "Quantity", sortable: true, className: "text-right tabular-nums" },
  { key: "cost_basis", label: "Cost basis", sortable: true, className: "text-right tabular-nums", render: (row) => money(String(row.cost_basis)), sortValue: (row) => row.cost_basis },
  { key: "current_price", label: "Current price", sortable: true, className: "text-right tabular-nums", render: (row) => money(row.current_price), sortValue: (row) => Number(row.current_price) },
  { key: "market_value", label: "Market value", sortable: true, className: "text-right tabular-nums", render: (row) => money(row.market_value), sortValue: (row) => Number(row.market_value) },
  { key: "unrealised_pnl", label: "Unrealised P&L", sortable: true, className: "text-right tabular-nums", render: (row) => <span className={Number(row.unrealised_pnl) >= 0 ? "text-mint" : "text-danger"}>{money(row.unrealised_pnl)}</span>, sortValue: (row) => Number(row.unrealised_pnl) },
  { key: "allocation", label: "Allocation", sortable: true, className: "text-right tabular-nums", render: (row) => row.allocation === null ? "Unavailable" : `${row.allocation.toFixed(2)}%`, sortValue: (row) => row.allocation ?? -1 },
];

export function PortfolioIntegration() {
  const [state, setState] = useState<SourceState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    fetch("/api/portfolio", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() : Promise.reject(new Error("unavailable")))
      .then((data: unknown) => { if (active) setState(isPortfolioApiResponse(data) ? { kind: "api", data } : { kind: "error" }); })
      .catch(() => { if (active) setState({ kind: "error" }); });
    return () => { active = false; };
  }, []);

  if (state.kind === "loading") return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-32 animate-pulse rounded-xl border border-slate-700/70 bg-[#111c24]" />)}</div>;
  if (state.kind === "error") return <ErrorState title="Portfolio data unavailable" description="The read-only portfolio source could not be loaded. No demo values are shown." />;

  const { data } = state;
  const holdingsAvailable = data.holdings.availability.availability === "available";
  const allocationAvailable = data.allocation.availability.availability === "available";
  const equityAvailable = data.portfolio_summary.availability.availability === "available" && data.portfolio_summary.portfolio_value !== null;
  const allocation = data.allocation.items.map((item, index) => ({ ...item, value: Number(item.weight_percent), colour: colours[index % colours.length] }));
  const tableRows: TablePosition[] = data.holdings.items.map((row) => ({ ...row, cost_basis: costBasis(row), allocation: data.portfolio_summary.holdings_market_value && Number(data.portfolio_summary.holdings_market_value) !== 0 ? (Number(row.market_value) / Number(data.portfolio_summary.holdings_market_value)) * 100 : null }));
  const equityMetric = equityAvailable
    ? { label: "Total equity", value: money(data.portfolio_summary.portfolio_value!), helper: `Portfolio data as of ${timestamp(data.portfolio_summary.as_of_utc)}`, tone: "neutral" as const }
    : { label: "Total equity", value: "Unavailable", helper: data.portfolio_summary.availability.reason, tone: "warning" as const };

  return <div className="space-y-6">
    <div className="space-y-1 text-[15px] text-slate-300">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className="font-medium text-slate-100">Local snapshot</span><span>·</span><span>{data.source_classification === "local_snapshot" ? "Complete" : "Partial"}</span><span>·</span><span>Portfolio data as of {timestamp(data.portfolio_summary.as_of_utc)}</span></div>
      <div>Loaded {timestamp(data.generated_at_utc)}</div>
    </div>
    {data.freshness.status === "stale" ? <p className="rounded-lg border border-amber/25 bg-amber/10 px-4 py-3 text-[15px] text-amber">Stale snapshot — portfolio data is older than the local freshness threshold.</p> : null}
    {!holdingsAvailable ? <>
      <div className="grid gap-4 sm:grid-cols-2">
        <MetricCard item={equityMetric} />
        <MetricCard item={{ label: "Holdings snapshot status", value: "Unavailable", helper: "No complete single-timestamp holdings snapshot", tone: "warning" }} />
      </div>
      <ChartCard title="Holdings snapshot unavailable">
        <p className="max-w-3xl text-[15px] leading-6 text-slate-300">Holdings are split across multiple timestamps. They are not combined, so allocation, contribution and current holdings cannot be shown safely.</p>
        <details className="mt-5 border-t border-slate-700/70 pt-4">
          <summary className="cursor-pointer text-base font-medium text-slate-200">Details</summary>
          <p className="mt-3 text-[15px] text-slate-300">{data.holdings.availability.reason}</p>
        </details>
      </ChartCard>
    </> : <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard item={equityMetric} />
        <MetricCard item={{ label: "Holdings value", value: money(data.portfolio_summary.holdings_market_value!), helper: `Holdings as of ${timestamp(data.holdings.as_of_utc)}`, tone: "neutral" }} />
        <MetricCard item={{ label: "Cash", value: data.cash.value ? money(data.cash.value) : "Unavailable", helper: data.cash.availability.reason, tone: "warning" }} />
        <MetricCard item={{ label: "Reconciliation", value: data.portfolio_summary.reconciliation.availability === "available" ? "Matched" : "Unavailable", helper: data.portfolio_summary.reconciliation.reason, tone: data.portfolio_summary.reconciliation.availability === "available" ? "positive" : "warning" }} />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <ChartCard title="Allocation" subtitle="Complete single-timestamp holdings snapshot">
          {allocationAvailable ? <div className="grid items-center gap-2 sm:grid-cols-[1fr_190px]"><div className="h-[330px]"><ResponsiveContainer><PieChart><Pie data={allocation} dataKey="value" nameKey="instrument" innerRadius={75} outerRadius={112}>{allocation.map((item) => <Cell key={item.instrument} fill={item.colour} />)}</Pie><Tooltip formatter={(value: number) => `${value.toFixed(2)}%`} /></PieChart></ResponsiveContainer></div><div className="space-y-3 text-[15px]">{allocation.map((item) => <div key={item.instrument} className="flex items-center justify-between gap-2 text-slate-300"><span className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.colour }} />{item.instrument}</span><b className="tabular-nums text-slate-100">{item.value.toFixed(2)}%</b></div>)}</div></div> : null}
        </ChartCard>
        <ChartCard title="Contribution to return" subtitle="Requires a complete comparable holdings snapshot"><p className="text-[15px] text-slate-300">Contribution is available only when a comparable holdings source is supplied.</p></ChartCard>
      </div>
      <ChartCard title="Holdings" subtitle={`Complete snapshot as of ${timestamp(data.holdings.as_of_utc)}`}>{tableRows.length ? <DataTable data={tableRows} columns={positionColumns} /> : <EmptyState title="No holdings in snapshot" description="The latest complete portfolio snapshot contains no positions." />}</ChartCard>
    </>}
  </div>;
}
