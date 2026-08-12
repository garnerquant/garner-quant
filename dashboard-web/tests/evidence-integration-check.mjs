import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";

const resources = ["signals", "markets", "research", "shadow-runs", "risk-health", "audit"];
const client = readFileSync("components/DashboardClient.tsx", "utf8");
const integration = readFileSync("components/EvidenceIntegration.tsx", "utf8");
for (const resource of resources) {
  const route = readFileSync(`app/api/${resource}/route.ts`, "utf8");
  assert.match(route, /export async function GET/);
  assert.doesNotMatch(route, /POST|PUT|PATCH|DELETE/);
  assert.match(route, new RegExp(`/api/v1/${resource}`));
  assert.match(client, new RegExp(`resource="${resource}"`));
}
assert.match(integration, /No trustworthy evidence/);
assert.match(integration, /source_classification/);
assert.doesNotMatch(integration, /mockData|provider|export results/);
assert.doesNotMatch(client, /UploadCloud|Add a mock input file|mock_input|type=["']file|Advanced export settings|exportOn|attached/);
assert.match(client, /Manual comparison is unavailable in this read-only preview/);
assert.match(integration, /EVIDENCE UNAVAILABLE/);
assert.match(integration, /Overall health/);
assert.match(integration, /Evidence unavailable/);
assert.match(integration, /Runtime heartbeat/);
assert.match(integration, /Latest cycle/);
assert.match(integration, /Safety controls/);
assert.match(integration, /Monitor only/);
assert.doesNotMatch(integration, /92 \/ 100|Preview ready|System healthy/);
console.log("read-only evidence integration checks passed");
