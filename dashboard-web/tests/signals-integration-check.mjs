import { readFileSync } from "node:fs";

const integration = readFileSync("components/SignalsIntegration.tsx", "utf8");
const client = readFileSync("components/DashboardClient.tsx", "utf8");
const proxy = readFileSync("app/api/signals/route.ts", "utf8");

if (!integration.includes('fetch("/api/signals"')) throw new Error("Signals browser request must use the same-origin proxy");
if (!integration.includes('kind: "fallback"') || !integration.includes("Mock preview")) throw new Error("Signals must clearly fall back to mock data");
if (!integration.includes("No snapshot and mock values are combined")) throw new Error("Signals must not mix API and mock fields");
if (!integration.includes("Stale snapshot") || !integration.includes("Signals unavailable")) throw new Error("Signals must expose stale and unavailable states");
if (!proxy.includes("DASHBOARD_API_URL") || !proxy.includes("/api/v1/signals")) throw new Error("Signals proxy must be server-only");
if (!client.includes("Signals: integratedSignals")) throw new Error("Signals must use the integration component");
for (const page of ["Markets: markets", "Research: research", '"Shadow Runs": shadow', '"Risk & Health": risk', "Audit: audit"]) {
  if (!client.includes(page)) throw new Error(`${page} must remain on the mock preview`);
}

console.log("Signals integration checks passed");
