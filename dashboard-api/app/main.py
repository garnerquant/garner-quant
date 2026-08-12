from fastapi import FastAPI

from .models import OverviewResponse, PortfolioResponse
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
