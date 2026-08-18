"""
API REST d'accès en lecture aux données historiques du système.

Exposé sous /api/history/* via Nginx, documenté auto par FastAPI dans /api/docs.

Endpoints publics (GET, JSON) :
- /api/history/exchange-rates                → historique des cotations BCT
- /api/history/exchange-rates/currencies     → liste des devises disponibles
- /api/history/weather                       → historique météo par gouvernorat
- /api/history/weather/governorates          → liste des 24 gouvernorats
- /api/history/macro-indicators              → historique indicateurs macro BCT
- /api/history/macro-indicators/types        → liste des types d'indicateurs
- /api/history/energy/prices                 → historique prix énergie
- /api/history/energy/world-stats            → statistiques mondiales énergie
- /api/history/articles                      → liste articles générés
- /api/history/articles/{article_id}         → détail d'un article
- /api/history/executions                    → historique des exécutions d'agents
- /api/history/executions/{execution_id}     → détail d'une exécution
- /api/history/claude/costs                  → coûts Claude agrégés

Tous les endpoints supportent la pagination via `limit` (max 5000) et
`offset` (défaut 0). Les filtres sont passés en query params.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    ArticleGenerated,
    BctMacroIndicator,
    ClaudeLog,
    EnergyPrice,
    EnergyWorldStats,
    ExchangeRate,
    ExecutionLog,
    Governorate,
    WeatherData,
)

router = APIRouter(prefix="/history", tags=["history"])


# ============================================================
# Helpers de sérialisation
# ============================================================


def _decimal(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _iso_date(d: dt.date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _iso_datetime(d: dt.datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


# ============================================================
# 1. EXCHANGE RATES (BCT)
# ============================================================


@router.get(
    "/exchange-rates",
    summary="Historique des cotations BCT",
    response_model=dict[str, Any],
)
def get_exchange_rates(
    devise: str | None = Query(
        None,
        min_length=3,
        max_length=3,
        description="Code ISO 3 lettres de la devise (ex: USD, EUR, GBP). Insensible à la casse.",
    ),
    start_date: dt.date | None = Query(None, description="Date de cotation minimale (incluse)."),
    end_date: dt.date | None = Query(None, description="Date de cotation maximale (incluse)."),
    source_type: str | None = Query(
        None,
        description="Filtre par origine : 'daily_scrape', 'backfill_archive', 'manual'.",
    ),
    limit: int = Query(500, ge=1, le=5000, description="Nombre max de lignes."),
    offset: int = Query(0, ge=0, description="Offset pour pagination."),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Retourne les cotations BCT historiques, filtrables par devise et période.
    Ordre : `date_cotation` décroissant, puis `devise_code`.
    """
    stmt = select(ExchangeRate)
    if devise:
        stmt = stmt.where(ExchangeRate.devise_code == devise.upper())
    if start_date:
        stmt = stmt.where(ExchangeRate.date_cotation >= start_date)
    if end_date:
        stmt = stmt.where(ExchangeRate.date_cotation <= end_date)
    if source_type:
        stmt = stmt.where(ExchangeRate.source_type == source_type)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(
        ExchangeRate.date_cotation.desc(), ExchangeRate.devise_code.asc()
    ).limit(limit).offset(offset)

    rows = session.scalars(stmt).all()

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": r.id,
                "devise_code": r.devise_code,
                "date_cotation": _iso_date(r.date_cotation),
                "taux_achat": _decimal(r.taux_achat),
                "taux_vente": _decimal(r.taux_vente),
                "taux_moyen": _decimal(r.taux_moyen),
                "source_type": r.source_type,
                "fiabilite": r.fiabilite,
                "source_url": r.source_url,
                "timestamp_collecte": _iso_datetime(r.timestamp_collecte),
            }
            for r in rows
        ],
    }


@router.get(
    "/exchange-rates/currencies",
    summary="Liste des devises historisées avec bornes de dates",
)
def get_exchange_rates_currencies(
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """
    Pour chaque devise présente en base, retourne le nombre de cotations et
    les dates min / max disponibles. Utile pour construire dynamiquement un
    sélecteur de devises côté client.
    """
    stmt = select(
        ExchangeRate.devise_code,
        func.count(ExchangeRate.id).label("count"),
        func.min(ExchangeRate.date_cotation).label("date_min"),
        func.max(ExchangeRate.date_cotation).label("date_max"),
    ).group_by(ExchangeRate.devise_code).order_by(ExchangeRate.devise_code.asc())

    return [
        {
            "devise_code": row.devise_code,
            "count": row.count,
            "date_min": _iso_date(row.date_min),
            "date_max": _iso_date(row.date_max),
        }
        for row in session.execute(stmt).all()
    ]


# ============================================================
# 2. WEATHER (24 gouvernorats)
# ============================================================


@router.get(
    "/weather",
    summary="Historique météo par gouvernorat",
    response_model=dict[str, Any],
)
def get_weather_history(
    governorate: str | None = Query(
        None,
        description="Nom (fr) ou id du gouvernorat. Ex: 'Tunis', '1'.",
    ),
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Retourne les relevés météo historiques.
    Le champ `governorate` accepte soit un nom (case-insensitive) soit un id.
    """
    stmt = select(WeatherData, Governorate).join(
        Governorate, WeatherData.governorate_id == Governorate.id
    )
    if governorate:
        if governorate.isdigit():
            stmt = stmt.where(WeatherData.governorate_id == int(governorate))
        else:
            stmt = stmt.where(func.lower(Governorate.nom_fr) == governorate.lower())
    if start_date:
        stmt = stmt.where(WeatherData.date_cotation >= start_date)
    if end_date:
        stmt = stmt.where(WeatherData.date_cotation <= end_date)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(
        WeatherData.date_cotation.desc(), Governorate.ordre_affichage.asc()
    ).limit(limit).offset(offset)

    rows = session.execute(stmt).all()

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": w.id,
                "governorate_id": w.governorate_id,
                "governorate_nom_fr": g.nom_fr,
                "governorate_nom_en": g.nom_en,
                "date_cotation": _iso_date(w.date_cotation),
                "temperature_min": _decimal(w.temperature_min),
                "temperature_max": _decimal(w.temperature_max),
                "temperature_actuelle": _decimal(w.temperature_actuelle),
                "conditions": w.conditions,
                "humidite": w.humidite,
                "vent_vitesse": _decimal(w.vent_vitesse),
                "vent_direction": w.vent_direction,
                "pression": w.pression,
                "indice_uv": _decimal(w.indice_uv),
                "precipitations_mm": _decimal(w.precipitations_mm),
                "source": w.source,
                "fiabilite": w.fiabilite,
                "timestamp_collecte": _iso_datetime(w.timestamp_collecte),
            }
            for (w, g) in rows
        ],
    }


@router.get(
    "/weather/governorates",
    summary="Liste des 24 gouvernorats de Tunisie",
)
def get_governorates(
    active_only: bool = Query(True, description="Ne retourne que les gouvernorats actifs."),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(Governorate).order_by(Governorate.ordre_affichage.asc())
    if active_only:
        stmt = stmt.where(Governorate.actif.is_(True))
    return [
        {
            "id": g.id,
            "nom_fr": g.nom_fr,
            "nom_ar": g.nom_ar,
            "nom_en": g.nom_en,
            "latitude": _decimal(g.latitude),
            "longitude": _decimal(g.longitude),
            "region": g.region,
            "actif": g.actif,
        }
        for g in session.scalars(stmt).all()
    ]


# ============================================================
# 3. MACRO INDICATORS (BCT)
# ============================================================


@router.get(
    "/macro-indicators",
    summary="Historique des indicateurs macroéconomiques BCT",
    response_model=dict[str, Any],
)
def get_macro_indicators(
    indicateur_type: str | None = Query(
        None,
        description="Code indicateur (ex: M0, M3, RESERVES_DEVISES, TAUX_DIRECTEUR).",
    ),
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(BctMacroIndicator)
    if indicateur_type:
        stmt = stmt.where(BctMacroIndicator.indicateur_type == indicateur_type)
    if start_date:
        stmt = stmt.where(BctMacroIndicator.date_cotation >= start_date)
    if end_date:
        stmt = stmt.where(BctMacroIndicator.date_cotation <= end_date)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(
        BctMacroIndicator.date_cotation.desc(),
        BctMacroIndicator.indicateur_type.asc(),
    ).limit(limit).offset(offset)

    rows = session.scalars(stmt).all()

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": r.id,
                "indicateur_type": r.indicateur_type,
                "valeur": _decimal(r.valeur),
                "unite": r.unite,
                "date_cotation": _iso_date(r.date_cotation),
                "source_url": r.source_url,
                "fiabilite": r.fiabilite,
                "timestamp_collecte": _iso_datetime(r.timestamp_collecte),
            }
            for r in rows
        ],
    }


@router.get(
    "/macro-indicators/types",
    summary="Liste des types d'indicateurs macro disponibles",
)
def get_macro_indicator_types(
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(
        BctMacroIndicator.indicateur_type,
        func.count(BctMacroIndicator.id).label("count"),
        func.min(BctMacroIndicator.date_cotation).label("date_min"),
        func.max(BctMacroIndicator.date_cotation).label("date_max"),
    ).group_by(BctMacroIndicator.indicateur_type).order_by(
        BctMacroIndicator.indicateur_type.asc()
    )

    return [
        {
            "indicateur_type": row.indicateur_type,
            "count": row.count,
            "date_min": _iso_date(row.date_min),
            "date_max": _iso_date(row.date_max),
        }
        for row in session.execute(stmt).all()
    ]


# ============================================================
# 4. ENERGY (prix + stats mondiales)
# ============================================================


@router.get(
    "/energy/prices",
    summary="Historique des prix énergie collectés",
    response_model=dict[str, Any],
)
def get_energy_prices(
    energy_type: str | None = Query(
        None,
        description="Type d'énergie : 'gasoline', 'diesel', 'electricity', 'gas', etc.",
    ),
    pays_code: str | None = Query(None, description="Code pays ISO 3 lettres."),
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(EnergyPrice)
    if energy_type:
        stmt = stmt.where(EnergyPrice.energy_type == energy_type)
    if pays_code:
        stmt = stmt.where(EnergyPrice.pays_code == pays_code.upper())
    if start_date:
        stmt = stmt.where(EnergyPrice.date_collecte >= start_date)
    if end_date:
        stmt = stmt.where(EnergyPrice.date_collecte <= end_date)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(EnergyPrice.date_collecte.desc()).limit(limit).offset(offset)
    rows = session.scalars(stmt).all()

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": r.id,
                "energy_type": r.energy_type,
                "pays_code": r.pays_code,
                "pays_nom": r.pays_nom,
                "prix_usd": _decimal(r.prix_usd),
                "prix_tnd": _decimal(r.prix_tnd),
                "unite": r.unite,
                "taux_usd_tnd_utilise": _decimal(r.taux_usd_tnd_utilise),
                "date_donnee_source": _iso_date(r.date_donnee_source),
                "date_collecte": _iso_date(r.date_collecte),
                "source": r.source,
                "source_url": r.source_url,
                "fiabilite": r.fiabilite,
            }
            for r in rows
        ],
    }


@router.get(
    "/energy/world-stats",
    summary="Statistiques mondiales par type d'énergie",
    response_model=dict[str, Any],
)
def get_energy_world_stats(
    energy_type: str | None = Query(None),
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(EnergyWorldStats)
    if energy_type:
        stmt = stmt.where(EnergyWorldStats.energy_type == energy_type)
    if start_date:
        stmt = stmt.where(EnergyWorldStats.date_collecte >= start_date)
    if end_date:
        stmt = stmt.where(EnergyWorldStats.date_collecte <= end_date)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(EnergyWorldStats.date_collecte.desc()).limit(limit).offset(offset)
    rows = session.scalars(stmt).all()

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": r.id,
                "energy_type": r.energy_type,
                "moyenne_mondiale_usd": _decimal(r.moyenne_mondiale_usd),
                "rang_tunisie": r.rang_tunisie,
                "nombre_pays_classement": r.nombre_pays_classement,
                "pays_moins_cher_code": r.pays_moins_cher_code,
                "pays_moins_cher_nom": r.pays_moins_cher_nom,
                "pays_moins_cher_prix_usd": _decimal(r.pays_moins_cher_prix_usd),
                "pays_plus_cher_code": r.pays_plus_cher_code,
                "pays_plus_cher_nom": r.pays_plus_cher_nom,
                "pays_plus_cher_prix_usd": _decimal(r.pays_plus_cher_prix_usd),
                "date_donnee_source": _iso_date(r.date_donnee_source),
                "date_collecte": _iso_date(r.date_collecte),
                "source": r.source,
            }
            for r in rows
        ],
    }


# ============================================================
# 5. ARTICLES générés
# ============================================================


@router.get(
    "/articles",
    summary="Liste des articles générés",
    response_model=dict[str, Any],
)
def get_articles(
    theme: str | None = Query(
        None,
        description="Thème : meteo, taux_change, billets_monnaies, recap_economique, energie_carburant, …",
    ),
    langue: str | None = Query(None, description="Langue : fr, en."),
    statut: str | None = Query(
        None, description="Statut : draft, published, review_required."
    ),
    since: dt.date | None = Query(None, description="Date de publication minimale."),
    until: dt.date | None = Query(None, description="Date de publication maximale."),
    hallucination: str | None = Query(
        None, description="Filtre check anti-hallucination : passed, suspected."
    ),
    include_html: bool = Query(
        False, description="Inclure le HTML complet (attention volumineux)."
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Liste des articles générés (métadonnées). Le contenu HTML complet n'est
    inclus que si `include_html=true`. Pour les gros dumps, préférer
    l'endpoint article-par-id.
    """
    stmt = select(ArticleGenerated)
    if theme:
        stmt = stmt.where(ArticleGenerated.theme == theme)
    if langue:
        stmt = stmt.where(ArticleGenerated.langue == langue)
    if statut:
        stmt = stmt.where(ArticleGenerated.statut == statut)
    if since:
        stmt = stmt.where(ArticleGenerated.date_publication >= since)
    if until:
        stmt = stmt.where(ArticleGenerated.date_publication <= until)
    if hallucination:
        stmt = stmt.where(ArticleGenerated.hallucination_check == hallucination)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(
        ArticleGenerated.date_publication.desc(),
        ArticleGenerated.langue.asc(),
    ).limit(limit).offset(offset)

    rows = session.scalars(stmt).all()

    def _row(a: ArticleGenerated) -> dict[str, Any]:
        base = {
            "id": a.id,
            "execution_id": str(a.execution_id),
            "theme": a.theme,
            "date_publication": _iso_date(a.date_publication),
            "langue": a.langue,
            "titre_editorial": a.titre_editorial,
            "titre_seo": a.titre_seo,
            "slug": a.slug,
            "meta_description": a.meta_description,
            "focus_keyword": a.focus_keyword,
            "mots_cles": a.mots_cles,
            "statut": a.statut,
            "hallucination_check": a.hallucination_check,
            "wordpress_post_id": a.wordpress_post_id,
            "wordpress_post_url": a.wordpress_post_url,
            "file_path": a.file_path,
            "modele_claude_utilise": a.modele_claude_utilise,
            "date_validation": _iso_datetime(a.date_validation),
            "journaliste_validateur": a.journaliste_validateur,
            "created_at": _iso_datetime(a.created_at),
        }
        if include_html:
            base["contenu_html"] = a.contenu_html
        return base

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [_row(a) for a in rows],
    }


@router.get(
    "/articles/{article_id}",
    summary="Détail complet d'un article (HTML + méta + hallucination_details)",
)
def get_article(
    article_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    article = session.get(ArticleGenerated, article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article #{article_id} introuvable")

    return {
        "id": article.id,
        "execution_id": str(article.execution_id),
        "theme": article.theme,
        "date_publication": _iso_date(article.date_publication),
        "langue": article.langue,
        "titre_editorial": article.titre_editorial,
        "titre_seo": article.titre_seo,
        "slug": article.slug,
        "meta_description": article.meta_description,
        "focus_keyword": article.focus_keyword,
        "mots_cles": article.mots_cles,
        "contenu_html": article.contenu_html,
        "categorie_wordpress": article.categorie_wordpress,
        "image_wordpress_id": article.image_wordpress_id,
        "wordpress_post_id": article.wordpress_post_id,
        "wordpress_post_url": article.wordpress_post_url,
        "file_path": article.file_path,
        "statut": article.statut,
        "hallucination_check": article.hallucination_check,
        "hallucination_details": article.hallucination_details,
        "modele_claude_utilise": article.modele_claude_utilise,
        "date_validation": _iso_datetime(article.date_validation),
        "journaliste_validateur": article.journaliste_validateur,
        "created_at": _iso_datetime(article.created_at),
        "updated_at": _iso_datetime(article.updated_at),
    }


# ============================================================
# 6. EXECUTIONS d'agents
# ============================================================


@router.get(
    "/executions",
    summary="Historique des exécutions d'agents (résumé par execution_id)",
    response_model=dict[str, Any],
)
def get_executions(
    agent_name: str | None = Query(
        None, description="Filtrer par agent (weather, exchange_rates, saturday, sunday, energy_carburant)."
    ),
    since: dt.datetime | None = Query(None, description="Timestamp minimal."),
    until: dt.datetime | None = Query(None, description="Timestamp maximal."),
    status: str | None = Query(None, description="Filtre par statut du dernier step."),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Retourne un résumé par exécution (execution_id) avec le premier et dernier
    step, la durée, le statut final. Un run = plusieurs steps loggés.
    """
    sub_first = select(
        ExecutionLog.execution_id,
        ExecutionLog.agent_name,
        func.min(ExecutionLog.timestamp).label("started_at"),
        func.max(ExecutionLog.timestamp).label("finished_at"),
        func.count(ExecutionLog.id).label("steps_count"),
    ).group_by(ExecutionLog.execution_id, ExecutionLog.agent_name)

    if agent_name:
        sub_first = sub_first.where(ExecutionLog.agent_name == agent_name)
    if since:
        sub_first = sub_first.having(func.min(ExecutionLog.timestamp) >= since)
    if until:
        sub_first = sub_first.having(func.min(ExecutionLog.timestamp) <= until)

    sub = sub_first.subquery()

    stmt = select(sub).order_by(sub.c.started_at.desc()).limit(limit).offset(offset)
    total = session.scalar(select(func.count()).select_from(sub))
    rows = session.execute(stmt).all()

    # Pour chaque execution_id, on récupère le status du dernier step
    execution_ids = [r.execution_id for r in rows]
    final_steps: dict[uuid.UUID, dict] = {}
    if execution_ids:
        last_stmt = select(
            ExecutionLog.execution_id,
            ExecutionLog.status,
            ExecutionLog.agent_step,
            ExecutionLog.message,
        ).where(ExecutionLog.execution_id.in_(execution_ids)).order_by(
            ExecutionLog.execution_id, ExecutionLog.timestamp.desc()
        )
        for row in session.execute(last_stmt).all():
            if row.execution_id not in final_steps:
                final_steps[row.execution_id] = {
                    "final_status": row.status,
                    "final_step": row.agent_step,
                    "final_message": row.message,
                }

    result: list[dict[str, Any]] = []
    for r in rows:
        final = final_steps.get(r.execution_id, {})
        if status and final.get("final_status") != status:
            continue
        result.append({
            "execution_id": str(r.execution_id),
            "agent_name": r.agent_name,
            "started_at": _iso_datetime(r.started_at),
            "finished_at": _iso_datetime(r.finished_at),
            "duration_ms": int((r.finished_at - r.started_at).total_seconds() * 1000)
                if r.started_at and r.finished_at else None,
            "steps_count": r.steps_count,
            "final_status": final.get("final_status"),
            "final_step": final.get("final_step"),
            "final_message": final.get("final_message"),
        })

    return {
        "total": total,
        "count": len(result),
        "limit": limit,
        "offset": offset,
        "data": result,
    }


@router.get(
    "/executions/{execution_id}",
    summary="Détail d'une exécution (tous les steps loggés)",
)
def get_execution_detail(
    execution_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        exec_uuid = uuid.UUID(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="execution_id invalide (UUID attendu)") from exc

    stmt = select(ExecutionLog).where(
        ExecutionLog.execution_id == exec_uuid
    ).order_by(ExecutionLog.timestamp.asc())
    steps = session.scalars(stmt).all()

    if not steps:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} introuvable")

    # Articles produits par cette exécution
    art_stmt = select(ArticleGenerated).where(ArticleGenerated.execution_id == exec_uuid)
    articles = session.scalars(art_stmt).all()

    # Coûts Claude cumulés pour cette exécution
    cost_stmt = select(
        func.sum(ClaudeLog.cout_estime_usd).label("cout_total_usd"),
        func.sum(ClaudeLog.tokens_input).label("tokens_input"),
        func.sum(ClaudeLog.tokens_output).label("tokens_output"),
        func.sum(ClaudeLog.duree_ms).label("duree_ms"),
    ).where(ClaudeLog.execution_id == exec_uuid)
    cost = session.execute(cost_stmt).one()

    return {
        "execution_id": execution_id,
        "agent_name": steps[0].agent_name,
        "started_at": _iso_datetime(steps[0].timestamp),
        "finished_at": _iso_datetime(steps[-1].timestamp),
        "steps": [
            {
                "step": s.agent_step,
                "status": s.status,
                "message": s.message,
                "duree_ms": s.duree_ms,
                "payload_json": s.payload_json,
                "timestamp": _iso_datetime(s.timestamp),
            }
            for s in steps
        ],
        "articles": [
            {
                "id": a.id,
                "langue": a.langue,
                "titre_editorial": a.titre_editorial,
                "statut": a.statut,
                "hallucination_check": a.hallucination_check,
                "wordpress_post_url": a.wordpress_post_url,
                "file_path": a.file_path,
            }
            for a in articles
        ],
        "claude_usage": {
            "cout_total_usd": _decimal(cost.cout_total_usd),
            "tokens_input": cost.tokens_input,
            "tokens_output": cost.tokens_output,
            "duree_ms": cost.duree_ms,
        },
    }


# ============================================================
# 7. CLAUDE COSTS
# ============================================================


@router.get(
    "/claude/costs",
    summary="Agrégation des coûts Claude (total ou par jour / thème / modèle)",
)
def get_claude_costs(
    group_by: str = Query(
        "total",
        pattern="^(total|day|theme|model|langue)$",
        description="Granularité : total, day, theme, model, langue.",
    ),
    since: dt.datetime | None = Query(None),
    until: dt.datetime | None = Query(None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Agrégation flexible des coûts et de la consommation tokens.
    Utile pour dashboards de suivi économique.
    """
    filters = []
    if since:
        filters.append(ClaudeLog.created_at >= since)
    if until:
        filters.append(ClaudeLog.created_at <= until)

    if group_by == "total":
        stmt = select(
            func.coalesce(func.sum(ClaudeLog.cout_estime_usd), 0).label("cout_total_usd"),
            func.coalesce(func.sum(ClaudeLog.tokens_input), 0).label("tokens_input"),
            func.coalesce(func.sum(ClaudeLog.tokens_output), 0).label("tokens_output"),
            func.coalesce(func.sum(ClaudeLog.tokens_cache_read), 0).label("tokens_cache_read"),
            func.count(ClaudeLog.id).label("calls"),
        )
        for f in filters:
            stmt = stmt.where(f)
        row = session.execute(stmt).one()
        return {
            "group_by": "total",
            "data": {
                "cout_total_usd": _decimal(row.cout_total_usd),
                "tokens_input": row.tokens_input,
                "tokens_output": row.tokens_output,
                "tokens_cache_read": row.tokens_cache_read,
                "calls": row.calls,
            },
        }

    group_col_map = {
        "day": func.date_trunc("day", ClaudeLog.created_at),
        "theme": ClaudeLog.theme,
        "model": ClaudeLog.modele_utilise,
        "langue": ClaudeLog.langue,
    }
    group_col = group_col_map[group_by]

    stmt = select(
        group_col.label("bucket"),
        func.coalesce(func.sum(ClaudeLog.cout_estime_usd), 0).label("cout_usd"),
        func.coalesce(func.sum(ClaudeLog.tokens_input), 0).label("tokens_input"),
        func.coalesce(func.sum(ClaudeLog.tokens_output), 0).label("tokens_output"),
        func.count(ClaudeLog.id).label("calls"),
    ).group_by("bucket").order_by("bucket")

    for f in filters:
        stmt = stmt.where(f)

    rows = session.execute(stmt).all()

    return {
        "group_by": group_by,
        "data": [
            {
                "bucket": (
                    _iso_datetime(row.bucket) if group_by == "day" else row.bucket
                ),
                "cout_usd": _decimal(row.cout_usd),
                "tokens_input": row.tokens_input,
                "tokens_output": row.tokens_output,
                "calls": row.calls,
            }
            for row in rows
        ],
    }
