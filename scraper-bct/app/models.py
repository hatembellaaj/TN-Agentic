"""
Modèles SQLAlchemy nécessaires au scraper-bct.
Source de vérité du schéma : editorial-core/alembic/versions/.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
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


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    devise_code: Mapped[str] = mapped_column(String(3))
    date_cotation: Mapped[dt.date] = mapped_column(Date)
    taux_achat: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    taux_vente: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    taux_moyen: Mapped[Decimal | None] = mapped_column(Numeric(15, 6))
    source_url: Mapped[str | None] = mapped_column(String(500))
    fiabilite: Mapped[str] = mapped_column(String(20))
    source_type: Mapped[str] = mapped_column(String(20), default="daily_scrape")
    raw_data_json: Mapped[dict | None] = mapped_column(JSONB)
    timestamp_collecte: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class BctMacroIndicator(Base):
    __tablename__ = "bct_macro_indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicateur_type: Mapped[str] = mapped_column(String(50))
    valeur: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unite: Mapped[str | None] = mapped_column(String(50))
    date_cotation: Mapped[dt.date] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(500))
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
