"""V2 precompute datasets: master, sectors, membership, prices, liquidity, cap, progress.

Revision ID: 0002_v2_precompute
Revises: 0001_initial
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_v2_precompute"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_ticker_master",
        sa.Column("ticker", sa.String(length=16), primary_key=True),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("security_type", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )
    op.create_index("ix_v2_ticker_master_exchange", "v2_ticker_master", ["exchange"])
    op.create_index("ix_v2_ticker_master_data_as_of", "v2_ticker_master", ["data_as_of"])

    op.create_table(
        "v2_sector_map",
        sa.Column("ticker", sa.String(length=16), primary_key=True),
        sa.Column("icb_level2_name", sa.String(length=128), nullable=False),
        sa.Column("icb_level2_code", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
    )

    op.create_table(
        "v2_index_membership",
        sa.Column("index_code", sa.String(length=32), primary_key=True),
        sa.Column("symbol_code", sa.String(length=16), primary_key=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
    )

    op.create_table(
        "v2_daily_prices",
        sa.Column("symbol_code", sa.String(length=16), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close_adj", sa.Float(), nullable=False),
        sa.Column("close_raw", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("matched_volume", sa.BigInteger(), nullable=True),
        sa.Column("matched_value", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("price_adjustment_basis", sa.String(length=32), nullable=False),
        sa.Column("volume_basis", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )
    op.create_index("ix_v2_daily_prices_data_as_of", "v2_daily_prices", ["data_as_of"])

    op.create_table(
        "v2_liquidity",
        sa.Column("symbol_code", sa.String(length=16), primary_key=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("adtv_median", sa.Float(), nullable=True),
        sa.Column("adv_median", sa.Float(), nullable=True),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("volume_basis", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )

    op.create_table(
        "v2_market_cap",
        sa.Column("symbol_code", sa.String(length=16), primary_key=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("shares_outstanding", sa.BigInteger(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("basis", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )

    op.create_table(
        "v2_corporate_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("exright_date", sa.Date(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("ratio", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=False),
    )
    op.create_index("ix_v2_corporate_actions_ticker", "v2_corporate_actions", ["ticker"])

    op.create_table(
        "v2_progress",
        sa.Column("kind", sa.String(length=32), primary_key=True),
        sa.Column("symbol", sa.String(length=16), primary_key=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("v2_progress")
    op.drop_index("ix_v2_corporate_actions_ticker", table_name="v2_corporate_actions")
    op.drop_table("v2_corporate_actions")
    op.drop_table("v2_market_cap")
    op.drop_table("v2_liquidity")
    op.drop_index("ix_v2_daily_prices_data_as_of", table_name="v2_daily_prices")
    op.drop_table("v2_daily_prices")
    op.drop_table("v2_index_membership")
    op.drop_table("v2_sector_map")
    op.drop_index("ix_v2_ticker_master_data_as_of", table_name="v2_ticker_master")
    op.drop_index("ix_v2_ticker_master_exchange", table_name="v2_ticker_master")
    op.drop_table("v2_ticker_master")
