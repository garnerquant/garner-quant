import { readFileSync } from "node:fs";

const integration = readFileSync("components/EvidenceIntegration.tsx", "utf8");
const client = readFileSync("components/DashboardClient.tsx", "utf8");
const proxy = readFileSync("app/api/signals/route.ts", "utf8");

if (!integration.includes('fetch(`/api/${resource}`')) throw new Error("Signals browser request must use the shared same-origin evidence proxy");
if (!integration.includes("setError") || !integration.includes("<ErrorState")) throw new Error("Signals must fail closed when the API is unavailable");
if (!integration.includes("data.freshness.status") || !integration.includes("No trustworthy evidence")) throw new Error("Signals must expose stale and unavailable states");
if (!proxy.includes("DASHBOARD_API_URL") || !proxy.includes("/api/v1/signals")) throw new Error("Signals proxy must be server-only");
if (!client.includes('Signals: <EvidenceIntegration resource="signals" version="signals.v1" title="Strategy signals"/>')) throw new Error("Signals must use the read-only evidence integration component");
if (client.includes("Signals: signalView")) throw new Error("Signals must not render the mock preview as API evidence");

console.log("Signals integration checks passed");
