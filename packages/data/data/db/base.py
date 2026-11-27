"""Engine and session factory selection from ``DATABASE_URL``.

Local development and tests use SQLite; production uses Postgres. Both are
driven by the single ``database_url`` setting. Schema changes go through Alembic
in production; :func:`create_all` exists only so tests can build a throwaway
database quickly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def connect_args_for(database_url: str) -> dict[str, object]:
    """Return the driver ``connect_args`` implied by ``database_url``.

    SQLite needs ``check_same_thread=False`` because FastAPI may touch the
    connection from a worker thread. The Postgres deployment runs against a
    pgbouncer transaction pooler (Supabase port 6543), which cannot keep
    server-side prepared statements between transactions; psycopg3's automatic
    prepared statements then collide with "DuplicatePreparedStatement", so they
    are disabled for every psycopg connection. Remote Postgres connections also
    default to ``sslmode=require`` unless ``sslmode`` is already in the URL.
    """
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif database_url.startswith("postgresql+psycopg"):
        connect_args["prepare_threshold"] = None
        parsed = make_url(database_url)
        host = (parsed.host or "").lower()
        if host and host not in _LOCAL_HOSTS and "sslmode" not in parsed.query:
            connect_args["sslmode"] = "require"
    return connect_args


def create_engine_for(database_url: str) -> Engine:
    """Create an :class:`Engine` for ``database_url``."""
    return create_engine(
        database_url, future=True, connect_args=connect_args_for(database_url)
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    """Create every table (tests only; production uses Alembic)."""
    from data.db.models import Base

    Base.metadata.create_all(engine)
