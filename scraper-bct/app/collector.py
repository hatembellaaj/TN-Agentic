"""
Collecte BCT : fetch index.jsp → parse → persiste en base.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.bct_client import BctClient
from app.config import settings
from app.models import BctMacroIndicator, ExchangeRate, ExecutionLog
from app.parser import parse_bct_index, parse_indicators_page

logger = logging.getLogger(__name__)


def _decimal_or_none(v):
    return float(v) if v is not None else None


def collect_bct(session: Session, execution_id: uuid.UUID | None = None) -> dict[str, Any]:
    if execution_id is None:
        execution_id = uuid.uuid4()

    started = time.perf_counter()
    today = dt.date.today()

    # --- Fetch ---
    client = BctClient()
    try:
        html = client.fetch_index()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Echec fetch BCT")
        session.add(
            ExecutionLog(
                execution_id=execution_id,
                agent_name="scraper-bct",
                agent_step="fetch",
                status="error",
                message=str(exc),
                duree_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        session.commit()
        return {
            "execution_id": str(execution_id),
            "status": "error",
            "step": "fetch",
            "message": str(exc),
        }

    # --- Parse ---
    parsed = parse_bct_index(html)
    devises = parsed["devises"]
    indicators = parsed["indicators"]
    date_cotation = parsed["date_cotation"] or today

    devises_ok = 0
    indicators_ok = 0
    now_utc = dt.datetime.now(dt.timezone.utc)

    # --- Devises (upsert sur uq_rate_devise_date) ---
    for d in devises:
        try:
            taux = d["taux_moyen_pour_1"]
            stmt = pg_insert(ExchangeRate).values(
                devise_code=d["code"],
                date_cotation=date_cotation,
                # La BCT ne publie plus achat/vente séparés sur index.jsp → on alimente
                # les trois colonnes avec le taux moyen pour 1 unité.
                taux_achat=taux,
                taux_vente=taux,
                taux_moyen=taux,
                source_url=settings.BCT_INDEX_URL,
                fiabilite="haute",
                raw_data_json={
                    "unite_bct": d["unite"],
                    "valeur_brute": str(d["valeur_brute"]),
                    "raw_html": d["raw_html"],
                },
                timestamp_collecte=now_utc,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_rate_devise_date",
                set_={
                    "taux_achat": stmt.excluded.taux_achat,
                    "taux_vente": stmt.excluded.taux_vente,
                    "taux_moyen": stmt.excluded.taux_moyen,
                    "raw_data_json": stmt.excluded.raw_data_json,
                    "timestamp_collecte": now_utc,
                    "fiabilite": "haute",
                },
            )
            session.execute(stmt)
            devises_ok += 1
        except Exception:  # noqa: BLE001
            logger.exception("Echec insert devise %s", d.get("code"))

    # --- Indicateurs (insertion simple, pas d'unique constraint) ---
    for ind in indicators:
        try:
            session.add(
                BctMacroIndicator(
                    indicateur_type=ind["type"],
                    valeur=ind["valeur"],
                    unite=ind["unite"],
                    date_cotation=ind["date_cotation"] or today,
                    source_url=settings.BCT_INDEX_URL,
                    fiabilite="haute",
                    raw_data_json={
                        "periode_str": ind["periode_str"],
                        "raw_snippet": ind["raw_snippet"],
                    },
                    timestamp_collecte=now_utc,
                )
            )
            indicators_ok += 1
        except Exception:  # noqa: BLE001
            logger.exception("Echec insert indicateur %s", ind.get("type"))

    session.commit()

    duree_ms = int((time.perf_counter() - started) * 1000)
    fiabilite = (
        "haute"
        if (devises_ok >= 5 and indicators_ok >= 5)
        else "moyenne"
        if (devises_ok >= 3 or indicators_ok >= 3)
        else "basse"
    )

    session.add(
        ExecutionLog(
            execution_id=execution_id,
            agent_name="scraper-bct",
            agent_step="collect",
            status="success" if devises_ok > 0 else "error",
            message=f"{devises_ok} devises, {indicators_ok} indicateurs (fiabilite={fiabilite})",
            duree_ms=duree_ms,
            payload_json={
                "devises_ok": devises_ok,
                "indicators_ok": indicators_ok,
                "date_cotation": date_cotation.isoformat() if date_cotation else None,
            },
        )
    )
    session.commit()

    return {
        "execution_id": str(execution_id),
        "date_cotation": date_cotation.isoformat() if date_cotation else None,
        "devises_collectees": devises_ok,
        "indicateurs_collectes": indicators_ok,
        "fiabilite_globale": fiabilite,
        "duree_ms": duree_ms,
        "status": "success" if devises_ok > 0 else "error",
    }


# ============================================================
# Collecte indicateurs.jsp (Sprint 3)
# ============================================================

def collect_bct_indicators_detail(
    session: Session, execution_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """
    Collecte des 11 sections détaillées depuis indicateurs.jsp.

    Insère dans bct_macro_indicators avec des types distincts d'index.jsp
    (suffixe _detail pour les chevauchements, sinon types neufs).
    """
    if execution_id is None:
        execution_id = uuid.uuid4()

    started = time.perf_counter()
    now_utc = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()

    client = BctClient()
    try:
        html = client.fetch_indicators_page()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Echec fetch indicateurs.jsp")
        session.add(
            ExecutionLog(
                execution_id=execution_id,
                agent_name="scraper-bct",
                agent_step="fetch_indicators",
                status="error",
                message=str(exc),
                duree_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        session.commit()
        return {"execution_id": str(execution_id), "status": "error", "step": "fetch_indicators", "message": str(exc)}

    rows = parse_indicators_page(html)

    inserted = 0
    skipped = 0
    for row in rows:
        if row["valeur_principale"] is None:
            skipped += 1
            continue
        try:
            session.add(
                BctMacroIndicator(
                    indicateur_type=row["type"],
                    valeur=row["valeur_principale"],
                    unite=row["unite"],
                    date_cotation=row["date_cotation"] or today,
                    source_url=settings.BCT_INDICATORS_URL,
                    fiabilite="haute",
                    raw_data_json={
                        "section_id": row["section_id"],
                        "label": row["label"],
                        "row_label": row["row_label"],
                        "valeurs_brutes": row["valeurs_brutes"],
                        "raw_snippet": row["raw_snippet"],
                    },
                    timestamp_collecte=now_utc,
                )
            )
            inserted += 1
        except Exception:  # noqa: BLE001
            logger.exception("Echec insert section %s", row.get("type"))

    session.commit()

    duree_ms = int((time.perf_counter() - started) * 1000)
    session.add(
        ExecutionLog(
            execution_id=execution_id,
            agent_name="scraper-bct",
            agent_step="collect_indicators",
            status="success" if inserted > 0 else "error",
            message=f"{inserted} sections insérées, {skipped} ignorées (vides)",
            duree_ms=duree_ms,
            payload_json={"inserted": inserted, "skipped": skipped, "rows_parsed": len(rows)},
        )
    )
    session.commit()

    return {
        "execution_id": str(execution_id),
        "sections_inserees": inserted,
        "sections_ignorees": skipped,
        "sections_total": len(rows),
        "duree_ms": duree_ms,
        "status": "success" if inserted > 0 else "error",
    }


def collect_all_bct(session: Session, execution_id: uuid.UUID | None = None) -> dict[str, Any]:
    """
    Pipeline complet : index.jsp + indicateurs.jsp.
    Partage le même execution_id pour traçabilité bout en bout.
    """
    if execution_id is None:
        execution_id = uuid.uuid4()
    r1 = collect_bct(session, execution_id=execution_id)
    r2 = collect_bct_indicators_detail(session, execution_id=execution_id)
    return {
        "execution_id": str(execution_id),
        "status": "success" if r1.get("status") == "success" and r2.get("status") == "success" else "partial",
        "index_jsp": r1,
        "indicateurs_jsp": r2,
    }
