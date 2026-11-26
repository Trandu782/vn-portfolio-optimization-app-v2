"""Add query-performance indexes and widen v2_progress.state to VARCHAR(32).

Revision ID: 0006_v2_query_indexes
Revises: 0005_v2_financial_ratios
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_v2_query_indexes"
down_revision: str | None = "0005_v2_financial_ratios"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_v2_daily_prices_date", "v2_daily_prices", ["date"])
    op.create_index(
        "ix_v2_financial_ratios_period",
        "v2_financial_ratios",
        ["period", "period_type"],
    )
    with op.batch_alter_table("v2_progress") as batch_op:
        batch_op.alter_column(
            "state",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
            existing_server_default="pending",
        )


def downgrade() -> None:
    op.execute("UPDATE v2_progress SET state = 'done' WHERE length(state) > 16")
    with op.batch_alter_table("v2_progress") as batch_op:
        batch_op.alter_column(
            "state",
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
            existing_server_default="pending",
        )
    op.drop_index("ix_v2_financial_ratios_period", table_name="v2_financial_ratios")
    op.drop_index("ix_v2_daily_prices_date", table_name="v2_daily_prices")
