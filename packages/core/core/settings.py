"""Application settings and per-user settings.

``Settings`` is the single pydantic-settings module that reads environment
variables (prefix ``VNOPT_``). ``UserSettings`` holds values that belong to the
user (brokerage fee and risk-free rate). User values travel with every API
request and are persisted in the browser, so they are never hardcoded in domain
logic.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Allowed ranges for the user-controlled rates. These are validation limits,
# not user values: the user's chosen values and the defaults live only in
# ``UserSettings``.
BROKERAGE_FEE_RATE_MIN = Decimal("0")
BROKERAGE_FEE_RATE_MAX = Decimal("0.01")
RISK_FREE_RATE_MIN = 0.0
RISK_FREE_RATE_MAX = 0.20


class Settings(BaseSettings):
    """Process configuration read from environment variables prefixed ``VNOPT_``."""

    model_config = SettingsConfigDict(
        env_prefix="VNOPT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Efficient-frontier guardrails. The API reads these and passes them to the
    # frontier engine so a runaway random-portfolio cloud fails fast instead of
    # tripping the serverless limit. The hard cap is 100,000 portfolios: the engine
    # runs the whole simulation for the statistics and the API then plots a
    # stratified sample of `frontier_cloud_points` points, so a large run costs
    # compute but not response size (docs/Update patch v2.1.md).
    frontier_max_portfolios: int = 100_000
    frontier_time_budget: float = 30.0
    # Scatter points in a frontier response. The cloud statistics and the marked
    # portfolios always come from the full simulation; only the plotted sample is
    # capped. Configurable via VNOPT_FRONTIER_CLOUD_POINTS.
    frontier_cloud_points: int = Field(default=6_000, ge=1)

    # Maximum number of tickers the guided Optimize tab may send to the optimizer.
    # Configurable via VNOPT_MAX_OPTIMIZE_STOCKS; the default keeps the sample
    # covariance trustworthy. The UI reads the effective value from /optimize/options.
    max_optimize_stocks: int = 30

    # Comma-separated allowed CORS origins (VNOPT_CORS_ORIGINS). Wildcard '*' is
    # rejected; when empty, defaults to local Next.js dev origins in development
    # and [] in production.
    cors_origins: str = ""

    # Toggle for the in-memory API rate limiter (VNOPT_RATE_LIMIT_ENABLED).
    rate_limit_enabled: bool = True

    def parsed_cors_origins(self) -> list[str]:
        """Return allowed CORS origins, never allowing wildcard ``*``."""
        origins = [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip() and item.strip() != "*"
        ]
        if origins:
            return origins
        if self.environment.strip().lower() == "production":
            return []
        return ["http://localhost:3000", "http://127.0.0.1:3000"]


class UserSettings(BaseModel):
    """Values supplied by the user and sent with every API request.

    Both defaults are **placeholders** that the user is expected to replace: the
    fee default is a typical Vietnamese retail brokerage rate and the risk-free
    default is a convenient round number. Core functions receive these values as
    parameters; they are never read from global configuration or market rules.
    """

    brokerage_fee_rate: Decimal = Field(
        default=Decimal("0.0015"),
        description=(
            "Brokerage commission charged per side as a fraction of trade value "
            "(0.0015 == 0.15%). Default is a placeholder; check your broker's fee "
            "schedule."
        ),
    )
    risk_free_rate: float = Field(
        default=0.03,
        description=(
            "Annualized risk-free rate as a fraction (0.03 == 3%). Default is a "
            "placeholder; use a government bond yield appropriate for your horizon."
        ),
    )

    @field_validator("brokerage_fee_rate")
    @classmethod
    def _validate_brokerage_fee_rate(cls, value: Decimal) -> Decimal:
        """Reject a fee outside 0 to 0.01 (0% to 1%) with a clear message."""
        if not BROKERAGE_FEE_RATE_MIN <= value <= BROKERAGE_FEE_RATE_MAX:
            raise ValueError(
                "brokerage_fee_rate must be between 0 and 0.01 (0% and 1%); "
                f"got {value}."
            )
        return value

    @field_validator("risk_free_rate")
    @classmethod
    def _validate_risk_free_rate(cls, value: float) -> float:
        """Reject a risk-free rate outside 0 to 0.20 (0% to 20%) with a clear message."""
        if not RISK_FREE_RATE_MIN <= value <= RISK_FREE_RATE_MAX:
            raise ValueError(
                "risk_free_rate must be between 0 and 0.20 (0% and 20%); "
                f"got {value}."
            )
        return value
