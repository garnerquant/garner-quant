from fastapi import FastAPI

from .evidence import audit, markets, research, risk_health, shadow_runs, signals as evidence_signals
from .models import OverviewResponse, PortfolioResponse, ReadOnlyEvidenceResponse
from .overview import build_overview
from .portfolio import build_portfolio

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "dashboard-api"}


@app.get("/api/v1/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    return build_overview()


@app.get("/api/v1/portfolio", response_model=PortfolioResponse)
def portfolio() -> PortfolioResponse:
    return build_portfolio()


@app.get("/api/v1/signals", response_model=ReadOnlyEvidenceResponse)
def signal_evidence() -> ReadOnlyEvidenceResponse:
    return evidence_signals()


@app.get("/api/v1/markets", response_model=ReadOnlyEvidenceResponse)
def market_evidence() -> ReadOnlyEvidenceResponse:
    return markets()


@app.get("/api/v1/research", response_model=ReadOnlyEvidenceResponse)
def research_evidence() -> ReadOnlyEvidenceResponse:
    return research()


@app.get("/api/v1/shadow-runs", response_model=ReadOnlyEvidenceResponse)
def shadow_run_evidence() -> ReadOnlyEvidenceResponse:
    return shadow_runs()


@app.get("/api/v1/risk-health", response_model=ReadOnlyEvidenceResponse)
def risk_health_evidence() -> ReadOnlyEvidenceResponse:
    return risk_health()


@app.get("/api/v1/audit", response_model=ReadOnlyEvidenceResponse)
def audit_evidence() -> ReadOnlyEvidenceResponse:
    return audit()
