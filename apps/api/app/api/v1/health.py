"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Payload returned by the health check."""

    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
def read_health() -> HealthResponse:
    """Report that the API is up and serving requests."""
    return HealthResponse(
        status="ok",
        service="vn-portfolio-optimizer-api",
        version="0.1.0",
    )
