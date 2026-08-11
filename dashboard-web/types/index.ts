export type PageKey =
  | "Overview"
  | "Portfolio"
  | "Markets"
  | "Signals"
  | "Research"
  | "Shadow Runs"
  | "Risk & Health"
  | "Audit";

export type PageSlug =
  | "overview"
  | "portfolio"
  | "markets"
  | "signals"
  | "research"
  | "shadow-runs"
  | "risk-health"
  | "audit";

export type Signal = "BUY" | "HOLD" | "UNAVAILABLE";
export type Quality = "Verified" | "Stale" | "Unavailable";
export type ComparisonOutcome =
  | "Agree"
  | "Differ"
  | "Unavailable"
  | "Incomparable"
  | "Timing mismatch"
  | "Methodology mismatch";

export interface NavItem {
  label: PageKey;
  slug: PageSlug;
}

export interface Holding {
  instrument: string;
  name: string;
  assetClass: string;
  quantity: string;
  price: string;
  priceValue: number;
  weight: number;
  marketValue: number;
  dayPnl: number;
  totalPnl: number;
  signal: Signal;
  quality: Quality;
  currency: string;
  stop: string;
  target: string;
  avgCost: string;
  evidence: string;
  timestamp: string;
  listingCurrency: string;
  priceUnit: string;
  quantityPrecision: string;
}

export interface ChartPoint {
  date: string;
  portfolio?: number;
  benchmark?: number;
  drawdown?: number;
  volume?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  maShort?: number;
  maLong?: number;
  contribution?: number;
}

export interface MetricItem {
  label: string;
  value: string;
  change?: string;
  tone?: "positive" | "negative" | "warning" | "neutral";
  helper?: string;
}

export interface SignalRow {
  instrument: string;
  assetClass: string;
  signal: Signal;
  classification: string;
  evidence: string;
  eligibility: string;
  decision: string;
  execution: string;
  target: string;
  reason: string;
  quality: Quality;
  comparison: ComparisonOutcome;
}

export interface EvidenceRow {
  timestamp: string;
  runId: string;
  artifact: string;
  classification: string;
  hash: string;
  verification: string;
  dataset: string;
  code: string;
  mutability: "Immutable" | "Mutable";
  manifest: string[];
}

export interface StatusItem {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "warning" | "neutral";
}

export interface SelectOption {
  label: string;
  value: string;
}
