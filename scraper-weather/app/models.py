"""
Modèles SQLAlchemy nécessaires au scraper-weather.
Source de vérité du schéma : editorial-core/alembic/versions/.
Ce fichier ne fait que mapper les tables existantes pour l'accès en lecture/écriture.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Governorate(Base):
    __tablename__ = "governorates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nom_fr: Mapped[str] = mapped_column(String(100))
    nom_ar: Mapped[str | None] = mapped_column(String(100))
    nom_en: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    region: Mapped[str | None] = mapped_column(String(50))
    ordre_affichage: Mapped[int] = mapped_column(Integer)
    actif: Mapped[bool] = mapped_column(Boolean)


class WeatherData(Base):
    __tablename__ = "weather_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    governorate_id: Mapped[int] = mapped_column(ForeignKey("governorates.id"))
    date_cotation: Mapped[dt.date] = mapped_column(Date)

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
    source: Mapped[str] = mapped_column(String(50))
    fiabilite: Mapped[str] = mapped_column(String(20))
    raw_data_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp_collecte: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


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
