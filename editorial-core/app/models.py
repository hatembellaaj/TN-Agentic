"""
Modèles SQLAlchemy correspondant au schéma §7 du cahier des charges.
9 tables : governorates, weather_data, exchange_rates, bct_macro_indicators,
indicator_variations, articles_generated, claude_logs, execution_logs, notifications_log.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Classe de base avec colonnes communes created_at / updated_at."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ============================================================
# 7.2 governorates
# ============================================================
class Governorate(Base):
    __tablename__ = "governorates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom_fr: Mapped[str] = mapped_column(String(100), nullable=False)
    nom_ar: Mapped[str | None] = mapped_column(String(100))
    nom_en: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    region: Mapped[str | None] = mapped_column(String(50))
    capitale_gouvernorat: Mapped[bool] = mapped_column(Boolean, default=True)
    ordre_affichage: Mapped[int] = mapped_column(Integer, nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    weather_records: Mapped[list["WeatherData"]] = relationship(back_populates="governorate")


# ============================================================
# 7.3 weather_data
# ============================================================
class WeatherData(Base):
    __tablename__ = "weather_data"
    __table_args__ = (
        UniqueConstraint("governorate_id", "date_cotation", name="uq_weather_gov_date"),
        Index("ix_weather_date", "date_cotation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    governorate_id: Mapped[int] = mapped_column(
        ForeignKey("governorates.id", ondelete="CASCADE"), nullable=False
    )
    date_cotation: Mapped[dt.date] = mapped_column(Date, nullable=False)

    temperature_min: Mapped[float | None] = mapped_column(Numeric(5, 2))
    temperature_max: Mapped[float | None] = mapped_column(Numeric(5, 2))
    temperature_actuelle: Mapped[float | None] = mapped_column(Numeric(5, 2))
    conditions: Mapped[str | None] = mapped_column(String(100))
    humidite: Mapped[int | None] = mapped_column(Integer)
    vent_vitesse: Mapped[float | None] = mapped_column(Numeric(5, 2))
    vent_direction: Mapped[int | None] = mapped_column(Integer)
    pression: Mapped[int | None] = mapped_column(Integer)
    indice_uv: Mapped[float | None] = mapped_column(Numeric(4, 1))
    precipitations_mm: Mapped[float | None] = mapped_column(Numeric(6, 2))
    previsions_5j_json: Mapped[dict | None] = mapped_column(JSONB)

    source: Mapped[str] = mapped_column(String(50), default="openweathermap")
    fiabilite: Mapped[str] = mapped_column(String(20), default="haute")
    raw_data_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp_collecte: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    governorate: Mapped[Governorate] = relationship(back_populates="weather_records")


# ============================================================
# 7.4 exchange_rates (préparé pour Sprint 2)
# ============================================================
class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("devise_code", "date_cotation", name="uq_rate_devise_date"),
        Index("ix_rate_date", "date_cotation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    devise_code: Mapped[str] = mapped_column(String(3), nullable=False)
    date_cotation: Mapped[dt.date] = mapped_column(Date, nullable=False)
    taux_achat: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    taux_vente: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    taux_moyen: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    source_url: Mapped[str | None] = mapped_column(String(500))
    fiabilite: Mapped[str] = mapped_column(String(20), default="haute")
    # Origine de la donnée : 'daily_scrape' (cron quotidien index.jsp),
    # 'backfill_archive' (script de backfill via cours_archiv.jsp), 'manual'.
    source_type: Mapped[str] = mapped_column(String(20), default="daily_scrape", nullable=False)
    raw_data_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp_collecte: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ============================================================
# 7.5 bct_macro_indicators (préparé pour Sprint 3)
# ============================================================
class BctMacroIndicator(Base):
    __tablename__ = "bct_macro_indicators"
    __table_args__ = (
        Index("ix_macro_type_date", "indicateur_type", "date_cotation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicateur_type: Mapped[str] = mapped_column(String(50), nullable=False)
    valeur: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unite: Mapped[str | None] = mapped_column(String(50))
    date_cotation: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    fiabilite: Mapped[str] = mapped_column(String(20), default="haute")
    raw_data_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp_collecte: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ============================================================
# 7.6 indicator_variations (préparé pour Sprint 2 / 3)
# ============================================================
class IndicatorVariation(Base):
    __tablename__ = "indicator_variations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variation_j1: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    variation_j7: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    variation_j30: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    variation_j365: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    pourcentage_variation_j1: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    pourcentage_variation_j7: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    est_variation_notable: Mapped[bool] = mapped_column(Boolean, default=False)
    calculated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ============================================================
# 7.7 articles_generated
# ============================================================
class ArticleGenerated(Base):
    __tablename__ = "articles_generated"
    __table_args__ = (
        Index("ix_article_theme_date", "theme", "date_publication"),
        Index("ix_article_langue", "langue"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    theme: Mapped[str] = mapped_column(String(50), nullable=False)  # meteo, taux_change, billets_monnaies, recap_economique
    date_publication: Mapped[dt.date] = mapped_column(Date, nullable=False)
    langue: Mapped[str] = mapped_column(String(5), nullable=False)  # fr / en

    titre_editorial: Mapped[str] = mapped_column(String(500), nullable=False)
    titre_seo: Mapped[str | None] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_description: Mapped[str | None] = mapped_column(String(300))
    focus_keyword: Mapped[str | None] = mapped_column(String(100))
    mots_cles: Mapped[list | None] = mapped_column(JSONB)

    contenu_html: Mapped[str] = mapped_column(Text, nullable=False)
    image_wordpress_id: Mapped[int | None] = mapped_column(Integer)
    categorie_wordpress: Mapped[str | None] = mapped_column(String(100))

    wordpress_post_id: Mapped[int | None] = mapped_column(Integer)
    wordpress_post_url: Mapped[str | None] = mapped_column(String(500))
    file_path: Mapped[str | None] = mapped_column(String(500))  # ajout : chemin FilePublisher

    statut: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    hallucination_check: Mapped[str] = mapped_column(String(20), default="passed")
    hallucination_details: Mapped[dict | None] = mapped_column(JSONB)

    date_validation: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    journaliste_validateur: Mapped[str | None] = mapped_column(String(100))

    modele_claude_utilise: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_claude_response: Mapped[dict | None] = mapped_column(JSONB)


# ============================================================
# 7.8 claude_logs
# ============================================================
class ClaudeLog(Base):
    __tablename__ = "claude_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    theme: Mapped[str] = mapped_column(String(50), nullable=False)
    langue: Mapped[str | None] = mapped_column(String(5))
    prompt_envoye: Mapped[str | None] = mapped_column(Text)
    reponse_recue: Mapped[str | None] = mapped_column(Text)
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    tokens_cache_read: Mapped[int | None] = mapped_column(Integer)
    tokens_cache_creation: Mapped[int | None] = mapped_column(Integer)
    modele_utilise: Mapped[str] = mapped_column(String(50), nullable=False)
    cout_estime_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error_message: Mapped[str | None] = mapped_column(Text)


# ============================================================
# 7.9 execution_logs
# ============================================================
class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    __table_args__ = (Index("ix_exec_id", "execution_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_step: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ============================================================
# 7.10 notifications_log
# ============================================================
class NotificationLog(Base):
    __tablename__ = "notifications_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles_generated.id", ondelete="SET NULL")
    )
    destinataire: Mapped[str] = mapped_column(String(100), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), default="telegram")
    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    message_envoye: Mapped[str | None] = mapped_column(Text)
    timestamp_envoi: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    response_telegram_api: Mapped[dict | None] = mapped_column(JSONB)
