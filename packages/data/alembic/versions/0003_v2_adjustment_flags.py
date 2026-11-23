"""Persisted per-ticker adjustment-quality flags (computed by the precompute job).

Revision ID: 0003_v2_adjustment_flags
Revises: 0002_v2_precompute
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_v2_adjustment_flags"
down_revision: str | None = "0002_v2_precompute"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_adjustment_flags",
        sa.Column("ticker", sa.String(length=16), primary_key=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "exclude_from_group_indices",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("dates", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_v2_adjustment_flags_data_as_of", "v2_adjustment_flags", ["data_as_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_v2_adjustment_flags_data_as_of", table_name="v2_adjustment_flags")
    op.drop_table("v2_adjustment_flags")
