"""Tests for the engine connect-argument selection in ``data.db.base``."""

from __future__ import annotations

from data.db.base import connect_args_for


def test_sqlite_disables_the_thread_check() -> None:
    """SQLite connections must be usable across FastAPI worker threads."""
    assert connect_args_for("sqlite:///./vnopt.db") == {"check_same_thread": False}


def test_psycopg_disables_prepared_statements_and_enforces_tls_for_remote() -> None:
    """Remote psycopg URLs disable prepared statements and default to sslmode=require."""
    url = "postgresql+psycopg://user:pass@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"
    assert connect_args_for(url) == {"prepare_threshold": None, "sslmode": "require"}


def test_psycopg_local_and_explicit_sslmode_are_respected() -> None:
    """Localhost skips implicit sslmode and explicit query sslmode is not overwritten."""
    assert connect_args_for("postgresql+psycopg://user:pass@localhost:5432/db") == {
        "prepare_threshold": None
    }
    assert connect_args_for("postgresql+psycopg://user:pass@127.0.0.1:5432/db") == {
        "prepare_threshold": None
    }
    assert connect_args_for(
        "postgresql+psycopg://user:pass@remote.db:5432/db?sslmode=verify-full"
    ) == {"prepare_threshold": None}


def test_other_urls_need_no_connect_args() -> None:
    """A plain URL with no special driver gets the empty connect-args dict."""
    assert connect_args_for("postgresql://user:pass@host:5432/db") == {}
