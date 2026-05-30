"""
Dashboard de validation et de traçabilité.
Routes /dashboard/* rendues en Jinja2 + HTMX (UX progressive sans framework JS lourd).
"""
from __future__ import annotations

import datetime as dt
import uuid as uuid_mod
from pathlib import Path
from typing import Any

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import ArticleGenerated, ClaudeLog, ExchangeRate, ExecutionLog, NotificationLog

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def dashboard_home(
    request: Request,
    session: Session = Depends(get_session),
    theme: str | None = Query(None),
    langue: str | None = Query(None),
    statut: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Liste des articles générés avec filtres."""
    stmt = select(ArticleGenerated).order_by(desc(ArticleGenerated.created_at)).limit(200)
    if theme:
        stmt = stmt.where(ArticleGenerated.theme == theme)
    if langue:
        stmt = stmt.where(ArticleGenerated.langue == langue)
    if statut:
        stmt = stmt.where(ArticleGenerated.statut == statut)
    if date_from:
        stmt = stmt.where(ArticleGenerated.date_publication >= dt.date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(ArticleGenerated.date_publication <= dt.date.fromisoformat(date_to))

    articles = session.scalars(stmt).all()

    # Stats globales
    total_articles = session.scalar(select(func.count(ArticleGenerated.id))) or 0
    cout_total = session.scalar(select(func.coalesce(func.sum(ClaudeLog.cout_estime_usd), 0))) or 0
    cout_total_float = float(cout_total)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "articles": articles,
            "total_articles": total_articles,
            "cout_total_usd": round(cout_total_float, 4),
            "filters": {
                "theme": theme,
                "langue": langue,
                "statut": statut,
                "date_from": date_from,
                "date_to": date_to,
            },
        },
    )


@router.get("/articles/{article_id}", response_class=HTMLResponse)
def article_detail(
    article_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    article = session.get(ArticleGenerated, article_id)
    if not article:
        raise HTTPException(404, "Article inconnu")

    # Coût Claude pour cette exécution
    cost = session.scalar(
        select(func.coalesce(func.sum(ClaudeLog.cout_estime_usd), 0)).where(
            ClaudeLog.execution_id == article.execution_id
        )
    )
    tokens = session.execute(
        select(
            func.coalesce(func.sum(ClaudeLog.tokens_input), 0),
            func.coalesce(func.sum(ClaudeLog.tokens_output), 0),
            func.coalesce(func.sum(ClaudeLog.tokens_cache_read), 0),
        ).where(ClaudeLog.execution_id == article.execution_id)
    ).one()

    return templates.TemplateResponse(
        "article_detail.html",
        {
            "request": request,
            "article": article,
            "cost_usd": float(cost or 0),
            "tokens_input": int(tokens[0]),
            "tokens_output": int(tokens[1]),
            "tokens_cache_read": int(tokens[2]),
        },
    )


@router.get("/executions", response_class=HTMLResponse)
def executions_list(
    request: Request,
    session: Session = Depends(get_session),
):
    """Vue des exécutions récentes (par execution_id distinct)."""
    rows = session.execute(
        select(
            ExecutionLog.execution_id,
            func.min(ExecutionLog.timestamp).label("started_at"),
            func.max(ExecutionLog.timestamp).label("finished_at"),
            func.array_agg(ExecutionLog.agent_name).label("agents"),
            func.count(ExecutionLog.id).label("steps"),
            func.bool_or(ExecutionLog.status == "error").label("has_error"),
        )
        .group_by(ExecutionLog.execution_id)
        .order_by(desc("started_at"))
        .limit(50)
    ).all()

    return templates.TemplateResponse(
        "executions.html",
        {"request": request, "executions": rows},
    )


@router.get("/executions/{execution_id}", response_class=HTMLResponse)
def execution_detail(
    execution_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        exec_uuid = uuid_mod.UUID(execution_id)
    except ValueError as exc:
        raise HTTPException(400, "execution_id invalide") from exc

    steps = session.scalars(
        select(ExecutionLog)
        .where(ExecutionLog.execution_id == exec_uuid)
        .order_by(ExecutionLog.timestamp)
    ).all()
    articles = session.scalars(
        select(ArticleGenerated).where(ArticleGenerated.execution_id == exec_uuid)
    ).all()
    notifications = session.scalars(
        select(NotificationLog).where(
            NotificationLog.article_id.in_([a.id for a in articles])
        )
    ).all() if articles else []
    claude_calls = session.scalars(
        select(ClaudeLog).where(ClaudeLog.execution_id == exec_uuid)
    ).all()

    return templates.TemplateResponse(
        "execution_detail.html",
        {
            "request": request,
            "execution_id": execution_id,
            "steps": steps,
            "articles": articles,
            "notifications": notifications,
            "claude_calls": claude_calls,
        },
    )


# ============================================================
# Backfill historique BCT (UI)
# ============================================================

@router.get("/backfill", response_class=HTMLResponse)
def backfill_form(request: Request, session: Session = Depends(get_session)):
    """Formulaire de backfill : date_from + date_to + bouton."""
    # Quelques stats actuelles pour informer l'utilisateur
    stats = session.execute(
        select(
            func.min(ExchangeRate.date_cotation).label("oldest"),
            func.max(ExchangeRate.date_cotation).label("newest"),
            func.count(ExchangeRate.id).label("total"),
            func.count(func.distinct(ExchangeRate.date_cotation)).label("dates"),
        )
    ).one()
    backfill_count = session.scalar(
        select(func.count(ExchangeRate.id)).where(ExchangeRate.source_type == "backfill_archive")
    ) or 0
    daily_count = session.scalar(
        select(func.count(ExchangeRate.id)).where(ExchangeRate.source_type == "daily_scrape")
    ) or 0
    return templates.TemplateResponse(
        "backfill.html",
        {
            "request": request,
            "stats": {
                "oldest": stats.oldest.isoformat() if stats.oldest else None,
                "newest": stats.newest.isoformat() if stats.newest else None,
                "total": stats.total,
                "dates": stats.dates,
                "backfill_count": backfill_count,
                "daily_count": daily_count,
            },
            "scraper_url": settings.SCRAPER_BCT_URL,
        },
    )


# ============================================================
# Historique des cours par devise (UI + JSON pour Chart.js)
# ============================================================

@router.get("/exchange-rates", response_class=HTMLResponse)
def exchange_rates_page(
    request: Request,
    session: Session = Depends(get_session),
    devise: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Vue historique d'une devise (ou de toutes si devise non précisée)."""
    # Liste des devises disponibles
    devises_available = session.scalars(
        select(ExchangeRate.devise_code).distinct().order_by(ExchangeRate.devise_code)
    ).all()

    if devise == "ALL":
        devise = None

    # Range par défaut : 90 derniers jours
    today = dt.date.today()
    df = dt.date.fromisoformat(date_from) if date_from else today - dt.timedelta(days=90)
    dt_to = dt.date.fromisoformat(date_to) if date_to else today

    # Charge les données
    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.date_cotation >= df)
        .where(ExchangeRate.date_cotation <= dt_to)
        .order_by(ExchangeRate.date_cotation, ExchangeRate.devise_code)
    )
    if devise:
        stmt = stmt.where(ExchangeRate.devise_code == devise)

    rows = session.scalars(stmt).all()

    # Forme adaptée à Chart.js : un dataset par devise
    by_devise: dict[str, list[dict]] = {}
    for r in rows:
        by_devise.setdefault(r.devise_code, []).append(
            {
                "date": r.date_cotation.isoformat(),
                "taux_moyen": float(r.taux_moyen) if r.taux_moyen else None,
                "source_type": r.source_type,
            }
        )

    return templates.TemplateResponse(
        "exchange_rates.html",
        {
            "request": request,
            "devises_available": devises_available,
            "selected_devise": devise or "ALL",
            "date_from": df.isoformat(),
            "date_to": dt_to.isoformat(),
            "rows": rows,
            "by_devise_json": __import__("json").dumps(by_devise),
            "total_rows": len(rows),
        },
    )


@router.get("/exchange-rates/export.csv")
def exchange_rates_export_csv(
    session: Session = Depends(get_session),
    devise: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """
    Export CSV de l'historique des cours, en respectant les mêmes filtres
    (devise, date_from, date_to) que la page /dashboard/exchange-rates.

    Format CSV (séparateur virgule, encodage UTF-8 avec BOM pour ouverture
    directe dans Excel sans bug d'accents) :
      date_cotation,devise_code,taux_moyen,unite_bct,source_type,timestamp_collecte
    """
    if devise == "ALL":
        devise = None

    today = dt.date.today()
    df = dt.date.fromisoformat(date_from) if date_from else today - dt.timedelta(days=90)
    dt_to = dt.date.fromisoformat(date_to) if date_to else today

    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.date_cotation >= df)
        .where(ExchangeRate.date_cotation <= dt_to)
        .order_by(ExchangeRate.date_cotation, ExchangeRate.devise_code)
    )
    if devise:
        stmt = stmt.where(ExchangeRate.devise_code == devise)

    rows = session.scalars(stmt).all()

    # Construction du CSV en mémoire (StringIO) — pas de fichier disque
    buffer = io.StringIO()
    # BOM UTF-8 pour qu'Excel reconnaisse l'encodage et n'affiche pas "Ã©" au lieu de "é"
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=",", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "date_cotation",
        "devise_code",
        "taux_moyen_tnd",
        "unite_bct",
        "valeur_brute_bct",
        "source_type",
        "timestamp_collecte",
    ])
    for r in rows:
        raw = r.raw_data_json or {}
        writer.writerow([
            r.date_cotation.isoformat(),
            r.devise_code,
            f"{float(r.taux_moyen):.6f}" if r.taux_moyen is not None else "",
            raw.get("unite_bct", ""),
            raw.get("valeur_brute", ""),
            r.source_type,
            r.timestamp_collecte.isoformat() if r.timestamp_collecte else "",
        ])

    csv_data = buffer.getvalue()
    buffer.close()

    # Nom de fichier suggéré au navigateur
    devise_label = devise or "ALL"
    filename = f"bct_rates_{devise_label}_{df.isoformat()}_to_{dt_to.isoformat()}.csv"

    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
