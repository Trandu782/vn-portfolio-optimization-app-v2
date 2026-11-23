"""Initial data schema: symbols, prices, indices, constituents, sync log.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "symbols",
        sa.Column("code", sa.String(length=16), primary_key=True),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_symbols_exchange", "symbols", ["exchange"])

    op.create_table(
        "prices_daily",
        sa.Column(
            "symbol_code",
            sa.String(length=16),
            sa.ForeignKey("symbols.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("adj_close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
    )

    op.create_table(
        "indices_daily",
        sa.Column("index_code", sa.String(length=32), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("adj_close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
    )

    op.create_table(
        "index_constituents",
        sa.Column("index_code", sa.String(length=32), primary_key=True),
        sa.Column("symbol_code", sa.String(length=16), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("error_type", sa.String(length=32), nullable=True),
        sa.Column("rows_upserted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("message", sa.String(length=1024), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Reserved for V2 corporate-action data. Intentionally has no business columns.
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("corporate_actions")
    op.drop_table("sync_log")
    op.drop_table("index_constituents")
    op.drop_table("indices_daily")
    op.drop_table("prices_daily")
    op.drop_index("ix_symbols_exchange", table_name="symbols")
    op.drop_table("symbols")
