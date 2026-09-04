import { readFileSync } from "node:fs";

const integration = readFileSync("components/PortfolioIntegration.tsx", "utf8");
const client = readFileSync("components/DashboardClient.tsx", "utf8");
const proxy = readFileSync("app/api/portfolio/route.ts", "utf8");

if (!integration.includes('fetch("/api/portfolio"')) throw new Error("Portfolio browser request must use the same-origin proxy");
if (!integration.includes('kind: "error"') || !integration.includes("No demo values are shown")) throw new Error("Portfolio must clearly report API unavailability");
if (integration.includes("Mock preview") || integration.includes("fallback")) throw new Error("Portfolio must not render mock or fallback values");
if (!integration.includes("Portfolio data as of") || !integration.includes("Holdings snapshot status") || !integration.includes("Holdings snapshot unavailable") || !integration.includes("No complete single-timestamp holdings snapshot")) throw new Error("Portfolio partial state must be concise and clearly sourced");
if (integration.includes('title="Allocation unavailable"') || integration.includes('title="Contribution unavailable"') || integration.includes('title="Holdings unavailable"')) throw new Error("Portfolio partial state must use one holdings-unavailable panel");
if (!proxy.includes("DASHBOARD_API_URL") || !proxy.includes("/api/v1/portfolio")) throw new Error("Portfolio proxy is not server-only");
if (!client.includes("Portfolio: integratedPortfolio")) throw new Error("Portfolio must use the integration component");

console.log("Portfolio integration checks passed");
