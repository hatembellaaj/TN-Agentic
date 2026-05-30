"""ajout source_type sur exchange_rates pour distinguer scrape quotidien et backfill historique

Revision ID: 0002_source_type
Revises: 0001_initial
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_source_type"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 'daily_scrape' : ramassé par le cron quotidien depuis index.jsp / collect-all
    # 'backfill_archive' : ramassé par /scraper-bct/backfill depuis cours_archiv.jsp
    # 'manual' : inséré à la main pour test / rattrapage
    op.add_column(
        "exchange_rates",
        sa.Column("source_type", sa.String(20), server_default="daily_scrape", nullable=False),
    )
    op.create_index("ix_rate_source", "exchange_rates", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_rate_source", table_name="exchange_rates")
    op.drop_column("exchange_rates", "source_type")
