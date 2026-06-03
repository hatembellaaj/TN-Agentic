"""ajout tables energy_prices et energy_world_stats pour le cycle énergie mensuel

Revision ID: 0003_energy
Revises: 0002_source_type
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_energy"
down_revision: Union[str, None] = "0002_source_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- energy_prices : historisation prix par couple énergie/pays ----------
    op.create_table(
        "energy_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # energy_type : carburant_essence, carburant_gasoil, electricite_residentiel,
        # electricite_business, gaz_ville_menages
        sa.Column("energy_type", sa.String(50), nullable=False),
        sa.Column("pays_code", sa.String(3), nullable=False),  # ISO-2 (TN, DZ, MA, LY...) ou ISO-3
        sa.Column("pays_nom", sa.String(100), nullable=False),
        sa.Column("prix_usd", sa.Numeric(15, 6), nullable=False),
        sa.Column("prix_tnd", sa.Numeric(15, 6)),
        sa.Column("unite", sa.String(20), nullable=False),  # par_litre, par_kwh
        sa.Column("taux_usd_tnd_utilise", sa.Numeric(15, 6)),
        sa.Column("date_donnee_source", sa.Date()),
        sa.Column("date_collecte", sa.Date(), nullable=False),
        sa.Column("source", sa.String(50), server_default="GlobalPetrolPrices"),
        sa.Column("source_url", sa.String(500)),
        sa.Column("fiabilite", sa.String(20), server_default="haute"),
        sa.Column("raw_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_energy_prices_series",
        "energy_prices",
        ["energy_type", "pays_code", "date_collecte"],
    )
    op.create_index(
        "ix_energy_prices_compare",
        "energy_prices",
        ["energy_type", "date_collecte"],
    )

    # ---------- energy_world_stats : moyennes mondiales + rang Tunisie ----------
    op.create_table(
        "energy_world_stats",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("energy_type", sa.String(50), nullable=False),
        sa.Column("moyenne_mondiale_usd", sa.Numeric(15, 6)),
        sa.Column("rang_tunisie", sa.Integer()),
        sa.Column("nombre_pays_classement", sa.Integer()),
        sa.Column("pays_moins_cher_code", sa.String(3)),
        sa.Column("pays_moins_cher_nom", sa.String(100)),
        sa.Column("pays_moins_cher_prix_usd", sa.Numeric(15, 6)),
        sa.Column("pays_plus_cher_code", sa.String(3)),
        sa.Column("pays_plus_cher_nom", sa.String(100)),
        sa.Column("pays_plus_cher_prix_usd", sa.Numeric(15, 6)),
        sa.Column("date_donnee_source", sa.Date()),
        sa.Column("date_collecte", sa.Date(), nullable=False),
        sa.Column("source", sa.String(50), server_default="GlobalPetrolPrices"),
        sa.Column("source_url", sa.String(500)),
        sa.Column("raw_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_energy_world_stats_type_date",
        "energy_world_stats",
        ["energy_type", "date_collecte"],
    )


def downgrade() -> None:
    op.drop_index("ix_energy_world_stats_type_date", table_name="energy_world_stats")
    op.drop_table("energy_world_stats")
    op.drop_index("ix_energy_prices_compare", table_name="energy_prices")
    op.drop_index("ix_energy_prices_series", table_name="energy_prices")
    op.drop_table("energy_prices")
