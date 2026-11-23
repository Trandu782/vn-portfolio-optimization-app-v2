"""Alembic environment for the data package.

Imports the ORM metadata and reads the database URL from the same settings module
the app uses, so ``DATABASE_URL`` drives local SQLite and production Postgres.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Make ``data`` (this package) and ``core`` importable regardless of the cwd.
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # packages/data
sys.path.insert(0, str(_HERE.parents[2] / "core"))  # packages/core

from data.db.base import create_engine_for  # noqa: E402
from data.db.models import Base  # noqa: E402
from data.settings import get_settings  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations without a live connection (emit SQL)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    engine = create_engine_for(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
