"""
Agent samedi : article sur l'évolution hebdomadaire des billets et monnaies en circulation.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.claude_client import ClaudeClient, ClaudeJSONError
from app.config import settings
from app.hallucination_check import check_hallucinations
from app.models import ArticleGenerated, BctMacroIndicator, ExecutionLog
from app.prompts.saturday_billets import (
    REQUIRED_FIELDS, REQUIRED_LANGS, SATURDAY_SYSTEM_PROMPT, build_user_message,
)
from app.publishers import get_publisher
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def _log(session, exec_id, step, status, message=None, duree_ms=None, payload=None):
    session.add(ExecutionLog(
        execution_id=exec_id, agent_name="saturday_billets", agent_step=step,
        status=status, message=message, duree_ms=duree_ms, payload_json=payload,
    ))
    session.commit()


def _trigger_scrape_all(execution_id: uuid.UUID) -> dict[str, Any]:
    """Scrape index.jsp + indicateurs.jsp en un appel."""
    url = f"{settings.SCRAPER_BCT_URL.rstrip('/')}/collect-all"
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, json={"execution_id": str(execution_id)})
        r.raise_for_status()
        return r.json()


def _load_billets_history(session: Session) -> tuple[float | None, dt.date | None, list[dict[str, Any]]]:
    """
    Récupère la dernière valeur des billets en circulation + l'historique
    sur le dernier an (toutes sources combinées).
    """
    rows = session.scalars(
        select(BctMacroIndicator)
        .where(BctMacroIndicator.indicateur_type.in_(["billets_circulation", "billets_circulation_detail"]))
        .order_by(desc(BctMacroIndicator.date_cotation))
        .limit(400)
    ).all()
    if not rows:
        return None, None, []

    # Dédoublonne par date (priorité à l'entrée la plus récemment collectée)
    by_date: dict[dt.date, BctMacroIndicator] = {}
    for r in rows:
        if r.date_cotation not in by_date:
            by_date[r.date_cotation] = r

    sorted_dates = sorted(by_date.keys(), reverse=True)
    latest_date = sorted_dates[0]
    latest_val = float(by_date[latest_date].valeur)

    history = [
        {"date": d.isoformat(), "valeur": float(by_date[d].valeur)}
        for d in sorted_dates
    ]
    return latest_val, latest_date, history


def _load_contexte_macro(session: Session, date_ref: dt.date) -> dict[str, Any]:
    """Récupère les dernières valeurs des indicateurs macro pertinents."""
    contexte: dict[str, Any] = {}
    for ind_type in ["TMM", "taux_directeur", "avoirs_nets_mdt", "refinancement"]:
        latest = session.scalar(
            select(BctMacroIndicator)
            .where(BctMacroIndicator.indicateur_type == ind_type)
            .order_by(desc(BctMacroIndicator.date_cotation), desc(BctMacroIndicator.id))
        )
        if latest:
            contexte[ind_type] = {
                "valeur": float(latest.valeur),
                "unite": latest.unite,
                "date": latest.date_cotation.isoformat() if latest.date_cotation else None,
            }
    return contexte


def _validate_output(parsed: dict[str, Any]) -> str | None:
    for lang in REQUIRED_LANGS:
        block = parsed.get(lang)
        if not isinstance(block, dict):
            return f"Langue manquante : {lang}"
        for f in REQUIRED_FIELDS:
            if f not in block:
                return f"Champ manquant : {lang}.{f}"
    return None


def run_saturday_agent(
    session: Session,
    *,
    execution_id: uuid.UUID | None = None,
    trigger_scrape: bool = True,
) -> dict[str, Any]:
    if execution_id is None:
        execution_id = uuid.uuid4()

    started = time.perf_counter()

    # --- 1. Scrape complet (index + indicateurs) ---
    if trigger_scrape:
        try:
            sc = _trigger_scrape_all(execution_id)
            _log(session, execution_id, "scrape_all",
                 "success" if sc.get("status") == "success" else "partial",
                 message=str(sc.get("status")))
        except Exception as exc:  # noqa: BLE001
            _log(session, execution_id, "scrape_all", "error", message=str(exc))
            return {"execution_id": str(execution_id), "status": "error", "step": "scrape_all", "message": str(exc)}

    # --- 2. Chargement billets + historique ---
    valeur, date_ref, historique = _load_billets_history(session)
    if valeur is None or date_ref is None:
        msg = "Aucune valeur 'billets en circulation' en base."
        _log(session, execution_id, "load_data", "error", message=msg)
        return {"execution_id": str(execution_id), "status": "error", "step": "load_data", "message": msg}

    _log(session, execution_id, "load_data", "success",
         message=f"valeur={valeur} MDT au {date_ref}, {len(historique)} points d'historique")

    contexte_macro = _load_contexte_macro(session, date_ref)

    # --- 3. Claude ---
    user_msg = build_user_message(date_ref, valeur, historique, contexte_macro)
    claude = ClaudeClient()
    try:
        parsed = claude.generate_article(
            session=session, execution_id=execution_id, theme="billets_monnaies",
            system_prompt=SATURDAY_SYSTEM_PROMPT, user_message=user_msg,
        )
    except ClaudeJSONError as exc:
        _log(session, execution_id, "claude", "error", message=str(exc))
        return {"execution_id": str(execution_id), "status": "error", "step": "claude", "message": str(exc)}

    err = _validate_output(parsed)
    if err:
        _log(session, execution_id, "claude_validation", "error", message=err)
        return {"execution_id": str(execution_id), "status": "error", "step": "claude_validation", "message": err}

    _log(session, execution_id, "claude", "success")

    # --- 4. Anti-hallucination ---
    allowed_numbers: list[float] = [valeur]
    for h in historique:
        allowed_numbers.append(h["valeur"])
    for ind, info in contexte_macro.items():
        allowed_numbers.append(info["valeur"])
    fake_rows = [{"_v_" + str(i): v for i, v in enumerate(allowed_numbers) if v is not None}]

    publisher = get_publisher()
    articles_summary = []

    for lang in REQUIRED_LANGS:
        article = parsed[lang]
        check = check_hallucinations(article["contenu_html"], fake_rows)
        statut = "draft" if check["status"] == "passed" else "review_required"

        pub = publisher.publish(
            langue=lang, theme="billets_monnaies",
            date_publication=date_ref, article=article,
        )
        rec = ArticleGenerated(
            execution_id=execution_id, theme="billets_monnaies",
            date_publication=date_ref, langue=lang,
            titre_editorial=article["titre_editorial"][:500],
            titre_seo=(article.get("titre_seo") or "")[:200],
            slug=(article.get("slug") or "")[:255],
            meta_description=(article.get("meta_description") or "")[:300],
            focus_keyword=(article.get("focus_keyword") or "")[:100],
            mots_cles=article.get("mots_cles_secondaires"),
            contenu_html=article["contenu_html"],
            categorie_wordpress=article.get("categorie_suggeree"),
            wordpress_post_id=pub.backend_post_id,
            wordpress_post_url=pub.public_url if pub.backend == "wordpress" else None,
            file_path=pub.file_path,
            statut=statut, hallucination_check=check["status"],
            hallucination_details=check,
            modele_claude_utilise=claude.model, raw_claude_response=parsed,
        )
        session.add(rec); session.flush()

        articles_summary.append({
            "id": rec.id, "langue": lang, "titre": article["titre_editorial"],
            "public_url": pub.public_url,
            "dashboard_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/dashboard/articles/{rec.id}",
            "publish_success": pub.success,
            "hallucination_status": check["status"],
        })

    session.commit()
    _log(session, execution_id, "publish", "success")

    # --- 5. Telegram ---
    duree_total = int(time.perf_counter() - started)
    tg = TelegramClient()
    notif_ok = tg.notify_articles_generated(
        session=session, execution_id=execution_id, theme="billets_monnaies",
        date_iso=date_ref.isoformat(), articles_summary=articles_summary,
        modele=claude.model, duree_secondes=duree_total,
        statut="succès" if all(a["publish_success"] for a in articles_summary) else "partiel",
    )
    _log(session, execution_id, "telegram", "success" if notif_ok else "error")
    _log(session, execution_id, "pipeline_done", "success", duree_ms=duree_total * 1000)

    return {
        "execution_id": str(execution_id),
        "status": "success",
        "theme": "billets_monnaies",
        "date_publication": date_ref.isoformat(),
        "valeur_actuelle_mdt": valeur,
        "historique_size": len(historique),
        "duree_secondes": duree_total,
        "modele_claude": claude.model,
        "publisher": publisher.backend_name,
        "telegram_sent": notif_ok,
        "articles": articles_summary,
    }
