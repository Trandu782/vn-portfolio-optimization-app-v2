"""FastAPI application factory and entrypoint for the Vercel Python function."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.data import router as data_router
from app.api.v1.health import router as health_router
from app.api.v1.optimize import router as optimize_router
from app.api.v1.pnl import router as pnl_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.rebalance import router as rebalance_router
from app.api.v1.risk import router as risk_router
from app.api.v1.settings import router as settings_router
from app.api.v1.universe import router as universe_router
from app.api.v1.v2 import router as v2_router

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Build the FastAPI application.

    V1 exposes the health check, user settings and the Sharpe / rebalance cost
    calculations. Routes are versioned under ``/api/v1`` so future endpoints can
    be added without breaking clients.
    """
    application = FastAPI(
        title="VN Portfolio Optimizer API",
        version="0.1.0",
        description="Decision support only. Not financial advice.",
    )

    # The web app calls the API through a Next.js proxy, but a permissive CORS
    # policy keeps direct browser calls working during local development.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    application.include_router(health_router, prefix=API_V1_PREFIX)
    application.include_router(settings_router, prefix=API_V1_PREFIX)
    application.include_router(risk_router, prefix=API_V1_PREFIX)
    application.include_router(rebalance_router, prefix=API_V1_PREFIX)
    application.include_router(data_router, prefix=API_V1_PREFIX)
    application.include_router(universe_router, prefix=API_V1_PREFIX)
    application.include_router(portfolio_router, prefix=API_V1_PREFIX)
    application.include_router(pnl_router, prefix=API_V1_PREFIX)
    application.include_router(optimize_router, prefix=API_V1_PREFIX)
    application.include_router(v2_router, prefix=API_V1_PREFIX)
    return application


app = create_app()
