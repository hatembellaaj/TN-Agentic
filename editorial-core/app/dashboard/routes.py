"""
Dashboard de validation et de traçabilité.
Routes /dashboard/* rendues en Jinja2 + HTMX (UX progressive sans framework JS lourd).
"""
from __future__ import annotations

import datetime as dt
import uuid as uuid_mod
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ArticleGenerated, ClaudeLog, ExecutionLog, NotificationLog

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
