"""FastAPI application factory and entrypoint for the Vercel Python function."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from app.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from core.settings import Settings

API_V1_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the FastAPI application.

    V1 exposes the health check, user settings and the Sharpe / rebalance cost
    calculations. Routes are versioned under ``/api/v1`` so future endpoints can
    be added without breaking clients.
    """
    settings = Settings()
    is_production = settings.environment.strip().lower() == "production"

    application = FastAPI(
        title="VN Portfolio Optimizer API",
        version="0.1.0",
        description="Decision support only. Not financial advice.",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    @application.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg", "invalid input")),
                "type": str(err.get("type", "value_error")),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers={"Cache-Control": "no-store"},
        )

    # Middlewares wrap in reverse registration order, so CORSMiddleware runs outermost
    # and BodySizeLimitMiddleware runs closest to the router.
    application.add_middleware(BodySizeLimitMiddleware)
    application.add_middleware(
        RateLimitMiddleware, enabled=settings.rate_limit_enabled
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-Refresh-Token"],
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
