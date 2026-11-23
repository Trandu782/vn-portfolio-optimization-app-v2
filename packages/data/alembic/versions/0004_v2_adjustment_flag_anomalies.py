"""Add the per-anomaly `anomalies` column to the persisted adjustment flags.

Stores ``{date, exclude, category, reason}`` per dated anomaly so the Sector tab can
apply the group-index exclusion window-aware and label thin trading vs data glitches.

Revision ID: 0004_v2_adjustment_flag_anomalies
Revises: 0003_v2_adjustment_flags
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_v2_adjustment_flag_anomalies"
down_revision: str | None = "0003_v2_adjustment_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "v2_adjustment_flags",
        sa.Column("anomalies", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("v2_adjustment_flags", "anomalies")
