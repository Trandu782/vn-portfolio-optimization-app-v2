"""Tests for the engine connect-argument selection in ``data.db.base``."""

from __future__ import annotations

from data.db.base import connect_args_for


def test_sqlite_disables_the_thread_check() -> None:
    """SQLite connections must be usable across FastAPI worker threads."""
    assert connect_args_for("sqlite:///./vnopt.db") == {"check_same_thread": False}


def test_psycopg_disables_prepared_statements() -> None:
    """The pgbouncer pooler cannot keep named prepared statements, so disable them."""
    url = "postgresql+psycopg://user:pass@host:6543/postgres"
    assert connect_args_for(url) == {"prepare_threshold": None}


def test_other_urls_need_no_connect_args() -> None:
    """A plain URL with no special driver gets the empty connect-args dict."""
    assert connect_args_for("postgresql://user:pass@host:5432/db") == {}
