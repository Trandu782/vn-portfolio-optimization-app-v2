"""Add query-performance indexes on v2_daily_prices and v2_financial_ratios.

Revision ID: 0006_v2_query_indexes
Revises: 0005_v2_financial_ratios
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

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


def downgrade() -> None:
    op.drop_index("ix_v2_financial_ratios_period", table_name="v2_financial_ratios")
    op.drop_index("ix_v2_daily_prices_date", table_name="v2_daily_prices")
