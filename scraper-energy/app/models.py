"""Modèles SQLAlchemy partagés avec editorial-core."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Date, DateTime, Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EnergyPrice(Base):
    __tablename__ = "energy_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    energy_type: Mapped[str] = mapped_column(String(50))
    pays_code: Mapped[str] = mapped_column(String(3))
    pays_nom: Mapped[str] = mapped_column(String(100))
    prix_usd: Mapped[Decimal] = mapped_column(Numeric(15, 6))
    prix_tnd: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    unite: Mapped[str] = mapped_column(String(20))
    taux_usd_tnd_utilise: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    date_donnee_source: Mapped[dt.date | None] = mapped_column(Date)
    date_collecte: Mapped[dt.date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))
    fiabilite: Mapped[str] = mapped_column(String(20))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)


class EnergyWorldStats(Base):
    __tablename__ = "energy_world_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    energy_type: Mapped[str] = mapped_column(String(50))
    moyenne_mondiale_usd: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    rang_tunisie: Mapped[int | None] = mapped_column(Integer)
    nombre_pays_classement: Mapped[int | None] = mapped_column(Integer)
    pays_moins_cher_code: Mapped[str | None] = mapped_column(String(3))
    pays_moins_cher_nom: Mapped[str | None] = mapped_column(String(100))
    pays_moins_cher_prix_usd: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    pays_plus_cher_code: Mapped[str | None] = mapped_column(String(3))
    pays_plus_cher_nom: Mapped[str | None] = mapped_column(String(100))
    pays_plus_cher_prix_usd: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    date_donnee_source: Mapped[dt.date | None] = mapped_column(Date)
    date_collecte: Mapped[dt.date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)


class ExchangeRate(Base):
    """Lecture seule : pour récupérer le taux USD/TND."""
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    devise_code: Mapped[str] = mapped_column(String(3))
    date_cotation: Mapped[dt.date] = mapped_column(Date)
    taux_moyen: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    agent_name: Mapped[str] = mapped_column(String(50))
    agent_step: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text)
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
