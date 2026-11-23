"""V2b fundamentals: per-ticker ratios and precomputed sector statistics.

Revision ID: 0005_v2_financial_ratios
Revises: 0004_v2_adjustment_flag_anomalies
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_v2_financial_ratios"
down_revision: str | None = "0004_v2_adjustment_flag_anomalies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_financial_ratios",
        sa.Column("symbol_code", sa.String(length=16), primary_key=True),
        sa.Column("period", sa.Date(), primary_key=True),
        sa.Column("period_type", sa.String(length=16), primary_key=True),
        sa.Column("ratio_group", sa.String(length=16), nullable=False),
        sa.Column("ratios", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_v2_financial_ratios_data_as_of", "v2_financial_ratios", ["data_as_of"]
    )

    op.create_table(
        "v2_sector_statistics",
        sa.Column("sector", sa.String(length=128), primary_key=True),
        sa.Column("ratio", sa.String(length=48), primary_key=True),
        sa.Column("period", sa.Date(), primary_key=True),
        sa.Column("period_type", sa.String(length=16), primary_key=True),
        sa.Column("n", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("median", sa.Float(), nullable=True),
        sa.Column("mean", sa.Float(), nullable=True),
        sa.Column("winsorized_mean", sa.Float(), nullable=True),
        sa.Column("p5", sa.Float(), nullable=True),
        sa.Column("p95", sa.Float(), nullable=True),
        sa.Column("minimum", sa.Float(), nullable=True),
        sa.Column("maximum", sa.Float(), nullable=True),
        sa.Column("percentile_ranks", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_v2_sector_statistics_data_as_of", "v2_sector_statistics", ["data_as_of"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_sector_statistics_data_as_of", table_name="v2_sector_statistics"
    )
    op.drop_table("v2_sector_statistics")
    op.drop_index(
        "ix_v2_financial_ratios_data_as_of", table_name="v2_financial_ratios"
    )
    op.drop_table("v2_financial_ratios")
