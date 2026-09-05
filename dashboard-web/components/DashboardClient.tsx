"use client";

import { AppShell } from "@/components/AppShell";
import { EvidenceIntegration } from "@/components/EvidenceIntegration";
import { MarketsIntegration } from "@/components/MarketsIntegration";
import { OverviewIntegration } from "@/components/OverviewIntegration";
import { PortfolioIntegration } from "@/components/PortfolioIntegration";
import { PageKey } from "@/types";

export function DashboardClient({ page }: { page: PageKey }) {
  const view: Record<PageKey, React.ReactNode> = {
    Overview: <OverviewIntegration fallback={null} />,
    Portfolio: <PortfolioIntegration />,
    Markets: <MarketsIntegration />,
    Signals: <EvidenceIntegration resource="signals" version="signals.v1" title="Strategy signals" />,
    Research: <EvidenceIntegration resource="research" version="research.v1" title="Research run evidence" variant="research" />,
    "Shadow Runs": <EvidenceIntegration resource="shadow-runs" version="shadow-runs.v1" title="Shadow run evidence" variant="shadow-runs" emptyDescription="No verified shadow evaluation evidence is available." />,
    "Risk & Health": <EvidenceIntegration resource="risk-health" version="risk-health.v1" title="Safety and health evidence" variant="risk-health" />,
    Audit: <EvidenceIntegration resource="audit" version="audit.v1" title="Artifact verification evidence" variant="audit" />,
  };
  return <AppShell title={page}>{view[page]}</AppShell>;
}
