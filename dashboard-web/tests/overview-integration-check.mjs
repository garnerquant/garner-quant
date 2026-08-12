import { readFileSync } from "node:fs";

const integration = readFileSync("components/OverviewIntegration.tsx", "utf8");
const client = readFileSync("components/DashboardClient.tsx", "utf8");
const proxy = readFileSync("app/api/overview/route.ts", "utf8");

if (!integration.includes('fetch("/api/overview"')) throw new Error("Overview browser request must use the same-origin proxy");
if (!integration.includes('kind: "fallback"') || !integration.includes("Mock fallback")) throw new Error("Overview must clearly fall back to mock data");
if (!integration.includes("no snapshot and mock values are combined")) throw new Error("Overview must not mix API and mock fields");
if (!integration.includes("Local snapshot") || !integration.includes("Portfolio data as of") || !integration.includes("Loaded")) throw new Error("Overview must distinguish source and response timestamps");
if (!integration.includes("Stale snapshot") || !integration.includes("Latest recorded change")) throw new Error("Overview must present deterministic staleness and recorded-change provenance");
if (!integration.includes("snapshot_age_seconds") || integration.includes("Date.now")) throw new Error("Overview staleness must use API-provided age only");
if (!integration.includes("performanceDomain") || !integration.includes("displayCompactMoney") || !integration.includes("evenlySpacedTicks") || !integration.includes("labelFormatter") || !integration.includes("formatter={(value")) throw new Error("Portfolio chart must use compact GBP ticks, sparse dates, and exact tooltip formatting");
if (!integration.includes("Holdings have inconsistent timestamps") || integration.includes("description={data.allocation.availability.reason")) throw new Error("Overview allocation message must be human-readable");
if (!proxy.includes("DASHBOARD_API_URL") || !proxy.includes("/api/v1/overview")) throw new Error("Overview proxy is not server-only");
if (!client.includes("Overview: integratedOverview")) throw new Error("Only Overview may use the integration component");
const header = readFileSync("components/Header.tsx", "utf8");
if (!header.includes("Preview UI") || !header.includes("Monitor only") || header.includes("Local mock") || header.includes("11 Aug 2026")) throw new Error("Global header status indicators are incorrect");
for (const page of ["Markets: markets", "Signals: signalView", "Research: research", '"Shadow Runs": shadow', '"Risk & Health": risk', "Audit: audit"]) {
  if (!client.includes(page)) throw new Error(`${page} must remain on the mock preview`);
}

console.log("Overview integration checks passed");
