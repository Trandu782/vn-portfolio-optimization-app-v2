"""Process configuration for the data layer.

This is the data package's single ``pydantic-settings`` module. It reads
environment variables so no module hardcodes URLs, secrets or tuning numbers.
Most keys use the project-wide ``VNOPT_`` prefix; ``DATABASE_URL``,
``PROVIDER_ORDER`` and ``REFRESH_TOKEN`` additionally accept their bare names so
the deployment can use the conventional spellings ("selected by DATABASE_URL").

The default provider order (``kbs,vci,dnse,tcbs,ssi_iboard``) puts KBS first
because its public endpoints serve history, the symbol listing and index groups
anonymously; it can be overridden with ``VNOPT_PROVIDER_ORDER`` without a code
change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: Repository root. The default SQLite file is anchored here so the API (started
#: from ``apps/api``), Alembic (run from ``packages/data``) and the tests all use
#: the same database instead of creating an empty, unmigrated file per working
#: directory. ``DATABASE_URL`` still overrides this in production.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATABASE_URL = f"sqlite:///{(_REPO_ROOT / 'vnopt.db').as_posix()}"


class DataSettings(BaseSettings):
    """Tunables and secrets for providers, sync and persistence."""

    model_config = SettingsConfigDict(
        env_prefix="VNOPT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    database_url: str = Field(
        default=_DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices("DATABASE_URL", "VNOPT_DATABASE_URL"),
        description=(
            "SQLAlchemy URL. SQLite by default (anchored at the repository root), "
            "Postgres in production."
        ),
    )
    provider_order: str = Field(
        default="kbs,vci,dnse,tcbs,ssi_iboard",
        validation_alias=AliasChoices("PROVIDER_ORDER", "VNOPT_PROVIDER_ORDER"),
        description="Comma-separated failover order of provider ids.",
    )
    refresh_token: str = Field(
        default="",
        validation_alias=AliasChoices("REFRESH_TOKEN", "VNOPT_REFRESH_TOKEN"),
        description="Shared secret for the protected refresh/probe endpoints.",
    )

    user_agent: str = DEFAULT_USER_AGENT
    provider_timeout_seconds: float = 15.0
    provider_rate_limit_per_minute: int = 20
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    circuit_breaker_failures: int = 5
    circuit_breaker_cooldown_seconds: int = 300

    price_mismatch_tolerance: float = 0.005
    stale_window_days: int = 7
    stale_tolerance_days: int = 1

    # A nightly cron run processes one bounded batch: ``sync_batch_size`` symbols
    # or ``sync_time_budget_seconds``, whichever comes first. Raise both (and the
    # Vercel function ``maxDuration``) to cover a larger universe per run.
    sync_batch_size: int = 50
    sync_time_budget_seconds: int = 45
    on_demand_history_days: int = 365

    @property
    def provider_ids(self) -> list[str]:
        """Return the configured provider ids in failover order."""
        return [part.strip() for part in self.provider_order.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> DataSettings:
    """Return the process-wide settings singleton."""
    return DataSettings()
