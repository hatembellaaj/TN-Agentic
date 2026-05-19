"""initial schema — 9 tables du cahier des charges §7

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- governorates ----------
    op.create_table(
        "governorates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nom_fr", sa.String(100), nullable=False),
        sa.Column("nom_ar", sa.String(100)),
        sa.Column("nom_en", sa.String(100)),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("region", sa.String(50)),
        sa.Column("capitale_gouvernorat", sa.Boolean(), server_default=sa.true()),
        sa.Column("ordre_affichage", sa.Integer(), nullable=False),
        sa.Column("actif", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ---------- weather_data ----------
    op.create_table(
        "weather_data",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("governorate_id", sa.Integer(), sa.ForeignKey("governorates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date_cotation", sa.Date(), nullable=False),
        sa.Column("temperature_min", sa.Numeric(5, 2)),
        sa.Column("temperature_max", sa.Numeric(5, 2)),
        sa.Column("temperature_actuelle", sa.Numeric(5, 2)),
        sa.Column("conditions", sa.String(100)),
        sa.Column("humidite", sa.Integer()),
        sa.Column("vent_vitesse", sa.Numeric(5, 2)),
        sa.Column("vent_direction", sa.Integer()),
        sa.Column("pression", sa.Integer()),
        sa.Column("indice_uv", sa.Numeric(4, 1)),
        sa.Column("precipitations_mm", sa.Numeric(6, 2)),
        sa.Column("previsions_5j_json", postgresql.JSONB()),
        sa.Column("source", sa.String(50), server_default="openweathermap"),
        sa.Column("fiabilite", sa.String(20), server_default="haute"),
        sa.Column("raw_data_json", postgresql.JSONB()),
        sa.Column("timestamp_collecte", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("governorate_id", "date_cotation", name="uq_weather_gov_date"),
    )
    op.create_index("ix_weather_date", "weather_data", ["date_cotation"])

    # ---------- exchange_rates (Sprint 2) ----------
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("devise_code", sa.String(3), nullable=False),
        sa.Column("date_cotation", sa.Date(), nullable=False),
        sa.Column("taux_achat", sa.Numeric(15, 6)),
        sa.Column("taux_vente", sa.Numeric(15, 6)),
        sa.Column("taux_moyen", sa.Numeric(15, 6)),
        sa.Column("source_url", sa.String(500)),
        sa.Column("fiabilite", sa.String(20), server_default="haute"),
        sa.Column("raw_data_json", postgresql.JSONB()),
        sa.Column("timestamp_collecte", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("devise_code", "date_cotation", name="uq_rate_devise_date"),
    )
    op.create_index("ix_rate_date", "exchange_rates", ["date_cotation"])

    # ---------- bct_macro_indicators (Sprint 3) ----------
    op.create_table(
        "bct_macro_indicators",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("indicateur_type", sa.String(50), nullable=False),
        sa.Column("valeur", sa.Numeric(20, 6), nullable=False),
        sa.Column("unite", sa.String(50)),
        sa.Column("date_cotation", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(500)),
        sa.Column("fiabilite", sa.String(20), server_default="haute"),
        sa.Column("raw_data_json", postgresql.JSONB()),
        sa.Column("timestamp_collecte", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_macro_type_date", "bct_macro_indicators", ["indicateur_type", "date_cotation"])

    # ---------- indicator_variations ----------
    op.create_table(
        "indicator_variations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_table", sa.String(50), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("variation_j1", sa.Numeric(20, 6)),
        sa.Column("variation_j7", sa.Numeric(20, 6)),
        sa.Column("variation_j30", sa.Numeric(20, 6)),
        sa.Column("variation_j365", sa.Numeric(20, 6)),
        sa.Column("pourcentage_variation_j1", sa.Numeric(8, 4)),
        sa.Column("pourcentage_variation_j7", sa.Numeric(8, 4)),
        sa.Column("est_variation_notable", sa.Boolean(), server_default=sa.false()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ---------- articles_generated ----------
    op.create_table(
        "articles_generated",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("theme", sa.String(50), nullable=False),
        sa.Column("date_publication", sa.Date(), nullable=False),
        sa.Column("langue", sa.String(5), nullable=False),
        sa.Column("titre_editorial", sa.String(500), nullable=False),
        sa.Column("titre_seo", sa.String(200)),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("meta_description", sa.String(300)),
        sa.Column("focus_keyword", sa.String(100)),
        sa.Column("mots_cles", postgresql.JSONB()),
        sa.Column("contenu_html", sa.Text(), nullable=False),
        sa.Column("image_wordpress_id", sa.Integer()),
        sa.Column("categorie_wordpress", sa.String(100)),
        sa.Column("wordpress_post_id", sa.Integer()),
        sa.Column("wordpress_post_url", sa.String(500)),
        sa.Column("file_path", sa.String(500)),
        sa.Column("statut", sa.String(30), server_default="draft", nullable=False),
        sa.Column("hallucination_check", sa.String(20), server_default="passed"),
        sa.Column("hallucination_details", postgresql.JSONB()),
        sa.Column("date_validation", sa.DateTime(timezone=True)),
        sa.Column("journaliste_validateur", sa.String(100)),
        sa.Column("modele_claude_utilise", sa.String(50), nullable=False),
        sa.Column("raw_claude_response", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_article_theme_date", "articles_generated", ["theme", "date_publication"])
    op.create_index("ix_article_langue", "articles_generated", ["langue"])

    # ---------- claude_logs ----------
    op.create_table(
        "claude_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("theme", sa.String(50), nullable=False),
        sa.Column("langue", sa.String(5)),
        sa.Column("prompt_envoye", sa.Text()),
        sa.Column("reponse_recue", sa.Text()),
        sa.Column("tokens_input", sa.Integer()),
        sa.Column("tokens_output", sa.Integer()),
        sa.Column("tokens_cache_read", sa.Integer()),
        sa.Column("tokens_cache_creation", sa.Integer()),
        sa.Column("modele_utilise", sa.String(50), nullable=False),
        sa.Column("cout_estime_usd", sa.Numeric(10, 6)),
        sa.Column("duree_ms", sa.Integer()),
        sa.Column("status", sa.String(20), server_default="success"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ---------- execution_logs ----------
    op.create_table(
        "execution_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("agent_step", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("duree_ms", sa.Integer()),
        sa.Column("payload_json", postgresql.JSONB()),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_exec_id", "execution_logs", ["execution_id"])

    # ---------- notifications_log ----------
    op.create_table(
        "notifications_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles_generated.id", ondelete="SET NULL")),
        sa.Column("destinataire", sa.String(100), nullable=False),
        sa.Column("canal", sa.String(20), server_default="telegram"),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("message_envoye", sa.Text()),
        sa.Column("timestamp_envoi", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("response_telegram_api", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notifications_log")
    op.drop_index("ix_exec_id", table_name="execution_logs")
    op.drop_table("execution_logs")
    op.drop_table("claude_logs")
    op.drop_index("ix_article_langue", table_name="articles_generated")
    op.drop_index("ix_article_theme_date", table_name="articles_generated")
    op.drop_table("articles_generated")
    op.drop_table("indicator_variations")
    op.drop_index("ix_macro_type_date", table_name="bct_macro_indicators")
    op.drop_table("bct_macro_indicators")
    op.drop_index("ix_rate_date", table_name="exchange_rates")
    op.drop_table("exchange_rates")
    op.drop_index("ix_weather_date", table_name="weather_data")
    op.drop_table("weather_data")
    op.drop_table("governorates")
