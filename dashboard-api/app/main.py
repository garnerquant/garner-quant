from fastapi import FastAPI

from .models import OverviewResponse
from .overview import build_overview

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "dashboard-api"}


@app.get("/api/v1/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    return build_overview()
