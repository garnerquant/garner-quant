import {
  ChartPoint,
  ComparisonOutcome,
  EvidenceRow,
  Holding,
  MetricItem,
  NavItem,
  SelectOption,
  SignalRow,
  StatusItem,
} from "@/types";

export const navItems: NavItem[] = [
  { label: "Overview", slug: "overview" },
  { label: "Portfolio", slug: "portfolio" },
  { label: "Markets", slug: "markets" },
  { label: "Signals", slug: "signals" },
  { label: "Research", slug: "research" },
  { label: "Shadow Runs", slug: "shadow-runs" },
  { label: "Risk & Health", slug: "risk-health" },
  { label: "Audit", slug: "audit" },
];

export const dateRanges: SelectOption[] = [
  { label: "1M", value: "1m" },
  { label: "3M", value: "3m" },
  { label: "6M", value: "6m" },
  { label: "1Y", value: "1y" },
  { label: "YTD", value: "ytd" },
];

export const currencies: SelectOption[] = [
  { label: "GBP", value: "GBP" },
  { label: "USD", value: "USD" },
  { label: "EUR", value: "EUR" },
];

export const researchRuns: SelectOption[] = [
  { label: "Research Run R-2408-A", value: "R-2408-A" },
  { label: "Research Run R-2407-C", value: "R-2407-C" },
  { label: "Research Run R-2406-B", value: "R-2406-B" },
];

export const instrumentOptions: SelectOption[] = [
  { label: "IUSA.L", value: "IUSA.L" },
  { label: "VWRL.L", value: "VWRL.L" },
  { label: "AAPL", value: "AAPL" },
  { label: "BTC-GBP", value: "BTC-GBP" },
  { label: "SGLN.L", value: "SGLN.L" },
];

export const overviewMetrics: MetricItem[] = [
  { label: "Portfolio Value", value: "GBP 10,842.60", helper: "Base currency", tone: "neutral" },
  { label: "Today", value: "+0.42%", helper: "Versus prior close", tone: "positive" },
  { label: "Total Return", value: "+8.43%", helper: "1Y preview", tone: "positive" },
  { label: "Max Drawdown", value: "-4.18%", helper: "Trailing 1Y", tone: "negative" },
  { label: "Cash", value: "GBP 1,672.40", helper: "Available capital", tone: "neutral" },
  { label: "Gross Exposure", value: "84.6%", helper: "Monitor only", tone: "warning" },
];

export const portfolioMetrics: MetricItem[] = [
  { label: "Total Equity", value: "GBP 9,170.20", tone: "neutral" },
  { label: "Cash", value: "GBP 1,672.40", tone: "neutral" },
  { label: "Invested Capital", value: "GBP 8,876.54", tone: "neutral" },
  { label: "Realized P&L", value: "+GBP 412.36", tone: "positive" },
  { label: "Unrealized P&L", value: "+GBP 709.14", tone: "positive" },
  { label: "Income", value: "GBP 88.27", tone: "positive" },
  { label: "Fees", value: "-GBP 31.15", tone: "negative" },
  { label: "Exposure", value: "84.6%", tone: "warning" },
];

export const holdings: Holding[] = [
  {
    instrument: "VWRL.L",
    name: "Vanguard FTSE All-World",
    assetClass: "Equity ETF",
    quantity: "42.000",
    price: "GBP 104.79",
    priceValue: 104.79,
    weight: 40.6,
    marketValue: 4401.18,
    dayPnl: 32.16,
    totalPnl: 352.46,
    signal: "HOLD",
    quality: "Verified",
    currency: "GBP",
    stop: "GBP 94.00",
    target: "GBP 113.50",
    avgCost: "GBP 96.23",
    evidence: "Verified / 14m ago",
    timestamp: "11 Aug 2026, 15:44",
    listingCurrency: "GBP",
    priceUnit: "Per share",
    quantityPrecision: "3 decimals",
  },
  {
    instrument: "IUSA.L",
    name: "iShares Core S&P 500",
    assetClass: "Equity ETF",
    quantity: "18.000",
    price: "GBP 175.16",
    priceValue: 175.16,
    weight: 29.1,
    marketValue: 3152.88,
    dayPnl: 21.48,
    totalPnl: 211.33,
    signal: "BUY",
    quality: "Verified",
    currency: "GBP",
    stop: "GBP 161.00",
    target: "GBP 188.40",
    avgCost: "GBP 163.42",
    evidence: "Verified / 14m ago",
    timestamp: "11 Aug 2026, 15:44",
    listingCurrency: "GBP",
    priceUnit: "Per share",
    quantityPrecision: "3 decimals",
  },
  {
    instrument: "SGLN.L",
    name: "iShares Physical Gold",
    assetClass: "Commodities",
    quantity: "16.000",
    price: "GBP 32.51",
    priceValue: 32.51,
    weight: 4.8,
    marketValue: 520.16,
    dayPnl: -2.07,
    totalPnl: 18.72,
    signal: "HOLD",
    quality: "Verified",
    currency: "GBP",
    stop: "GBP 29.80",
    target: "GBP 36.00",
    avgCost: "GBP 31.27",
    evidence: "Verified / 14m ago",
    timestamp: "11 Aug 2026, 15:44",
    listingCurrency: "GBP",
    priceUnit: "Per share",
    quantityPrecision: "3 decimals",
  },
  {
    instrument: "AAPL",
    name: "Apple Inc.",
    assetClass: "Single Stock",
    quantity: "5.000",
    price: "GBP 173.22",
    priceValue: 173.22,
    weight: 8,
    marketValue: 866.10,
    dayPnl: 8.92,
    totalPnl: 54.19,
    signal: "BUY",
    quality: "Stale",
    currency: "USD",
    stop: "GBP 158.00",
    target: "GBP 190.00",
    avgCost: "GBP 161.58",
    evidence: "Stale / 2h ago",
    timestamp: "11 Aug 2026, 14:03",
    listingCurrency: "USD",
    priceUnit: "Per share",
    quantityPrecision: "3 decimals",
  },
  {
    instrument: "BTC-GBP",
    name: "Bitcoin / GBP",
    assetClass: "Digital asset",
    quantity: "0.012",
    price: "GBP 64,000.00",
    priceValue: 64000,
    weight: 7.1,
    marketValue: 768,
    dayPnl: -14.63,
    totalPnl: 72.44,
    signal: "UNAVAILABLE",
    quality: "Unavailable",
    currency: "GBP",
    stop: "N/A",
    target: "N/A",
    avgCost: "GBP 63,238.00",
    evidence: "Unavailable / source gap",
    timestamp: "11 Aug 2026, 12:30",
    listingCurrency: "GBP",
    priceUnit: "Per coin",
    quantityPrecision: "6 decimals",
  },
];

export const portfolioSeries: ChartPoint[] = [
  { date: "Aug 25", portfolio: 100.0, benchmark: 100.0 },
  { date: "Sep 25", portfolio: 101.8, benchmark: 101.2 },
  { date: "Oct 25", portfolio: 100.9, benchmark: 99.8 },
  { date: "Nov 25", portfolio: 104.2, benchmark: 103.5 },
  { date: "Dec 25", portfolio: 106.1, benchmark: 105.2 },
  { date: "Jan 26", portfolio: 105.3, benchmark: 104.9 },
  { date: "Feb 26", portfolio: 107.9, benchmark: 106.6 },
  { date: "Mar 26", portfolio: 106.7, benchmark: 105.7 },
  { date: "Apr 26", portfolio: 109.6, benchmark: 108.2 },
  { date: "May 26", portfolio: 108.8, benchmark: 108.6 },
  { date: "Jun 26", portfolio: 111.8, benchmark: 110.5 },
  { date: "Jul 26", portfolio: 107.7, benchmark: 107.2 },
  { date: "Aug 26", portfolio: 108.43, benchmark: 106.92 },
];

export const drawdownSeries: ChartPoint[] = portfolioSeries.map((point, index) => ({
  date: point.date,
  drawdown: [0, -0.4, -1.4, -0.2, -0.1, -1.0, 0, -1.1, -0.2, -0.8, 0, -4.18, -2.1][index],
}));

export const allocationByAsset = [
  { name: "Equity ETFs", value: 71, color: "#6dd8df" },
  { name: "Commodities", value: 5, color: "#89e3b7" },
  { name: "Single Stock", value: 8, color: "#f1b964" },
  { name: "Digital Asset", value: 7, color: "#6486b1" },
  { name: "Cash", value: 9, color: "#2a3a46" },
];

export const allocationByCurrency = [
  { name: "GBP", value: 64, color: "#6dd8df" },
  { name: "USD", value: 29, color: "#89e3b7" },
  { name: "Other", value: 7, color: "#2a3a46" },
];

export const recentSignals = [
  { instrument: "IUSA.L", action: "BUY", note: "Momentum re-entry confirmed", time: "15:42" },
  { instrument: "AAPL", action: "BUY", note: "Breakout above 30D range", time: "14:01" },
  { instrument: "BTC-GBP", action: "UNAVAILABLE", note: "Data provenance gap", time: "12:30" },
];

export const riskStatus: StatusItem[] = [
  { label: "Runtime", value: "Monitor only", tone: "warning" },
  { label: "Paper execution", value: "Disabled", tone: "negative" },
  { label: "Trading", value: "Disabled", tone: "negative" },
  { label: "Limits approved", value: "No", tone: "negative" },
  { label: "Data freshness", value: "Healthy", tone: "positive" },
  { label: "Accounting", value: "Reconciled", tone: "positive" },
  { label: "Evidence", value: "Unverified research", tone: "warning" },
];

export const contributionSeries: ChartPoint[] = [
  { date: "VWRL.L", contribution: 2.6 },
  { date: "IUSA.L", contribution: 3.2 },
  { date: "SGLN.L", contribution: 0.4 },
  { date: "AAPL", contribution: 1.1 },
  { date: "BTC-GBP", contribution: 1.13 },
];

export const signals: SignalRow[] = [
  {
    instrument: "IUSA.L",
    assetClass: "Equity ETF",
    signal: "BUY",
    classification: "Technical only",
    evidence: "Available",
    eligibility: "Eligible",
    decision: "11 Aug 2026 15:42",
    execution: "11 Aug 2026 16:00",
    target: "34.0%",
    reason: "MOM_12M | TREND_UP",
    quality: "Verified",
    comparison: "Agree",
  },
  {
    instrument: "VWRL.L",
    assetClass: "Equity ETF",
    signal: "HOLD",
    classification: "Technical only",
    evidence: "Available",
    eligibility: "Eligible",
    decision: "11 Aug 2026 15:42",
    execution: "11 Aug 2026 16:00",
    target: "40.6%",
    reason: "RISK_BUDGET | HOLD_BAND",
    quality: "Verified",
    comparison: "Agree",
  },
  {
    instrument: "SGLN.L",
    assetClass: "Commodities",
    signal: "HOLD",
    classification: "Technical only",
    evidence: "Available",
    eligibility: "Eligible",
    decision: "11 Aug 2026 15:42",
    execution: "11 Aug 2026 16:00",
    target: "5.0%",
    reason: "TREND_FLAT | HEDGE",
    quality: "Verified",
    comparison: "Timing mismatch",
  },
  {
    instrument: "AAPL",
    assetClass: "Single Stock",
    signal: "BUY",
    classification: "Technical only",
    evidence: "Partial",
    eligibility: "Eligible",
    decision: "11 Aug 2026 14:01",
    execution: "11 Aug 2026 16:00",
    target: "9.0%",
    reason: "MOM_6M | BREAKOUT",
    quality: "Stale",
    comparison: "Differ",
  },
  {
    instrument: "BTC-GBP",
    assetClass: "Digital asset",
    signal: "UNAVAILABLE",
    classification: "Technical only",
    evidence: "Unavailable",
    eligibility: "Blocked",
    decision: "11 Aug 2026 12:30",
    execution: "N/A",
    target: "0.0%",
    reason: "DATA_GAP | QUOTE_STALE",
    quality: "Unavailable",
    comparison: "Unavailable",
  },
];

export const marketSeries: ChartPoint[] = [
  { date: "05 Aug", open: 171.4, high: 173.5, low: 170.9, close: 172.6, volume: 420, maShort: 171.9, maLong: 169.8 },
  { date: "06 Aug", open: 172.6, high: 174.9, low: 171.9, close: 174.1, volume: 510, maShort: 172.5, maLong: 170.3 },
  { date: "07 Aug", open: 174.1, high: 175.1, low: 172.5, close: 173.3, volume: 388, maShort: 172.8, maLong: 170.9 },
  { date: "08 Aug", open: 173.3, high: 176.2, low: 173.0, close: 175.8, volume: 622, maShort: 173.6, maLong: 171.6 },
  { date: "09 Aug", open: 175.8, high: 176.8, low: 174.6, close: 176.1, volume: 570, maShort: 174.4, maLong: 172.4 },
  { date: "10 Aug", open: 176.1, high: 176.9, low: 173.4, close: 174.7, volume: 695, maShort: 174.8, maLong: 173.0 },
  { date: "11 Aug", open: 174.7, high: 175.8, low: 173.9, close: 175.16, volume: 462, maShort: 175.1, maLong: 173.7 },
];

export const comparisonOutcomes: ComparisonOutcome[] = [
  "Agree",
  "Differ",
  "Unavailable",
  "Incomparable",
  "Timing mismatch",
  "Methodology mismatch",
];

export const researchEquityCurve: ChartPoint[] = [
  { date: "Sep", portfolio: 100, benchmark: 100 },
  { date: "Oct", portfolio: 103.1, benchmark: 101.4 },
  { date: "Nov", portfolio: 105.8, benchmark: 102.9 },
  { date: "Dec", portfolio: 108.6, benchmark: 104.3 },
  { date: "Jan", portfolio: 107.4, benchmark: 103.5 },
  { date: "Feb", portfolio: 111.5, benchmark: 106.4 },
  { date: "Mar", portfolio: 109.0, benchmark: 104.8 },
  { date: "Apr", portfolio: 114.2, benchmark: 108.1 },
  { date: "May", portfolio: 113.1, benchmark: 107.6 },
  { date: "Jun", portfolio: 117.4, benchmark: 110.2 },
  { date: "Jul", portfolio: 114.0, benchmark: 108.9 },
  { date: "Aug", portfolio: 118.3, benchmark: 111.6 },
];

export const researchDrawdown: ChartPoint[] = [
  { date: "Sep", drawdown: -0.8 },
  { date: "Oct", drawdown: -1.4 },
  { date: "Nov", drawdown: 0 },
  { date: "Dec", drawdown: -0.2 },
  { date: "Jan", drawdown: -2.1 },
  { date: "Feb", drawdown: 0 },
  { date: "Mar", drawdown: -2.8 },
  { date: "Apr", drawdown: 0 },
  { date: "May", drawdown: -1.1 },
  { date: "Jun", drawdown: 0 },
  { date: "Jul", drawdown: -2.9 },
  { date: "Aug", drawdown: 0 },
];

export const monthlyReturns = [
  ["Sep", 1.8],
  ["Oct", -0.9],
  ["Nov", 3.3],
  ["Dec", 1.8],
  ["Jan", -0.7],
  ["Feb", 2.5],
  ["Mar", -1.1],
  ["Apr", 2.7],
  ["May", -0.7],
  ["Jun", 2.8],
  ["Jul", -3.7],
  ["Aug", 0.7],
] as const;

export const returnDistribution = [
  { bucket: "-4 to -2", value: 2 },
  { bucket: "-2 to 0", value: 3 },
  { bucket: "0 to 2", value: 4 },
  { bucket: "2 to 4", value: 2 },
  { bucket: "4 to 6", value: 1 },
];

export const auditRows: EvidenceRow[] = [
  {
    timestamp: "11 Aug 2026 15:44",
    runId: "ovr_20260811_1544",
    artifact: "Portfolio snapshot",
    classification: "Operational",
    hash: "a4d9c2e81d7fef31008e40a4731f0d4b7bf1",
    verification: "Verified",
    dataset: "prices-v2.4",
    code: "e94e1b5",
    mutability: "Immutable",
    manifest: ["positions.json", "nav_snapshot.json", "risk_summary.json"],
  },
  {
    timestamp: "11 Aug 2026 15:42",
    runId: "sig_20260811_1542",
    artifact: "Signal decision",
    classification: "Decision",
    hash: "782b19ddc4f7b6f44f4ef71ef95ea503f09a",
    verification: "Verified",
    dataset: "prices-v2.4",
    code: "e94e1b5",
    mutability: "Immutable",
    manifest: ["signals.csv", "decision_context.json", "benchmark_snapshot.json"],
  },
  {
    timestamp: "11 Aug 2026 15:39",
    runId: "rsk_20260811_1539",
    artifact: "Risk evaluation",
    classification: "Safety",
    hash: "e819aa41b58e0d3743b62085e4c98a9a09b2",
    verification: "Verified",
    dataset: "risk-v1.8",
    code: "e94e1b5",
    mutability: "Immutable",
    manifest: ["limits.yaml", "exposure_check.json", "freshness_audit.json"],
  },
  {
    timestamp: "11 Aug 2026 15:20",
    runId: "res_20260811_1520",
    artifact: "Research run",
    classification: "Research",
    hash: "d04c81be9f37a42cdecb1659ac6126cb2e19",
    verification: "Unverified",
    dataset: "research-2026.08",
    code: "c219d0a",
    mutability: "Immutable",
    manifest: ["equity_curve.csv", "turnover.csv", "parameters.json"],
  },
  {
    timestamp: "11 Aug 2026 14:03",
    runId: "mkt_20260811_1403",
    artifact: "Quote batch",
    classification: "Market data",
    hash: "5f0c3ebd0488fb07d75e2ef27c5aa3e6c85e",
    verification: "Partial",
    dataset: "quotes-v4.1",
    code: "e94e1b5",
    mutability: "Mutable",
    manifest: ["quotes.parquet", "provenance.json", "exceptions.log"],
  },
];

export const marketUnavailable = {
  instrument: "BTC-GBP",
  reason: "Preview source gap for provenance-complete bars.",
  freshness: "Unavailable",
};

export function formatMoney(value: number): string {
  const sign = value < 0 ? "-" : "";
  return `${sign}GBP ${Math.abs(value).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
