"""
Agent éditorial — semaine 1 du cycle énergie : carburant (essence + gasoil).

Orchestre : scrape GPP → lecture base → Claude FR+EN → publish WP → Telegram.
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
from app.models import ArticleGenerated, EnergyPrice, EnergyWorldStats, ExecutionLog
from app.prompts.energy_carburant import (
    ENERGY_CARBURANT_SYSTEM_PROMPT,
    REQUIRED_FIELDS,
    REQUIRED_LANGS,
    build_user_message,
)
from app.publishers import get_publisher
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


# URL du service scraper-energy (interne au réseau Docker)
SCRAPER_ENERGY_URL = "http://scraper-energy:8003"


def _log(session, exec_id, step, status, message=None, duree_ms=None, payload=None):
    session.add(ExecutionLog(
        execution_id=exec_id, agent_name="energy_carburant", agent_step=step,
        status=status, message=message, duree_ms=duree_ms, payload_json=payload,
    ))
    session.commit()


def _trigger_scrape(execution_id: uuid.UUID) -> dict[str, Any]:
    url = f"{SCRAPER_ENERGY_URL}/collect-fuel"
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, json={"execution_id": str(execution_id)})
        r.raise_for_status()
        return r.json()


def _load_latest_prices(
    session: Session, energy_type: str, today: dt.date
) -> tuple[list[dict[str, Any]], dt.date | None]:
    """
    Charge les prix les plus récents pour un type d'énergie, un par pays.
    Renvoie (prix par pays, date_donnee_source).
    """
    # Prend la date_collecte la plus récente disponible
    latest_collecte = session.scalar(
        select(EnergyPrice.date_collecte)
        .where(EnergyPrice.energy_type == energy_type)
        .order_by(desc(EnergyPrice.date_collecte))
        .limit(1)
    )
    if not latest_collecte:
        return [], None

    rows = session.scalars(
        select(EnergyPrice)
        .where(EnergyPrice.energy_type == energy_type)
        .where(EnergyPrice.date_collecte == latest_collecte)
        # On filtre les lignes "Tunisia (page détail)" pour ne pas avoir de doublon
        .where(EnergyPrice.pays_nom.not_like("%(page détail)%"))
    ).all()

    out = []
    for r in rows:
        out.append({
            "pays_code": r.pays_code,
            "pays_nom": r.pays_nom,
            "prix_usd": float(r.prix_usd),
            "prix_tnd": float(r.prix_tnd) if r.prix_tnd is not None else None,
            "unite": r.unite,
            "date_donnee_source": r.date_donnee_source.isoformat() if r.date_donnee_source else None,
        })
    # On déduplique par pays_code (au cas où plusieurs entrées même date)
    seen = set()
    deduped = []
    for r in out:
        if r["pays_code"] not in seen:
            seen.add(r["pays_code"])
            deduped.append(r)

    # Date donnée source (la plus récente parmi les rows)
    date_src = max(
        (r.date_donnee_source for r in rows if r.date_donnee_source),
        default=None,
    )
    return deduped, date_src


def _load_world_stats(session: Session, energy_type: str) -> dict[str, Any] | None:
    """Charge les stats mondiales les plus récentes pour un type d'énergie."""
    row = session.scalar(
        select(EnergyWorldStats)
        .where(EnergyWorldStats.energy_type == energy_type)
        .order_by(desc(EnergyWorldStats.date_collecte), desc(EnergyWorldStats.id))
        .limit(1)
    )
    if not row:
        return None
    return {
        "moyenne_mondiale_usd": float(row.moyenne_mondiale_usd) if row.moyenne_mondiale_usd else None,
        "rang_tunisie": row.rang_tunisie,
        "nombre_pays_classement": row.nombre_pays_classement,
        "pays_moins_cher_nom": row.pays_moins_cher_nom,
        "pays_moins_cher_prix_usd": float(row.pays_moins_cher_prix_usd) if row.pays_moins_cher_prix_usd else None,
        "pays_plus_cher_nom": row.pays_plus_cher_nom,
        "pays_plus_cher_prix_usd": float(row.pays_plus_cher_prix_usd) if row.pays_plus_cher_prix_usd else None,
        "date_donnee_source": row.date_donnee_source.isoformat() if row.date_donnee_source else None,
    }


def _validate_output(parsed: dict[str, Any]) -> str | None:
    for lang in REQUIRED_LANGS:
        block = parsed.get(lang)
        if not isinstance(block, dict):
            return f"Langue manquante : {lang}"
        for f in REQUIRED_FIELDS:
            if f not in block:
                return f"Champ manquant : {lang}.{f}"
    return None


def run_energy_carburant_agent(
    session: Session,
    *,
    execution_id: uuid.UUID | None = None,
    trigger_scrape: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """
    Pipeline complet pour l'article carburant (semaine 1 du cycle énergie).

    :param force: bypass de l'idempotence (republie même si article du mois existe).
    """
    if execution_id is None:
        execution_id = uuid.uuid4()
    started = time.perf_counter()
    today = dt.date.today()

    # --- 1. Scrape GPP ---
    if trigger_scrape:
        step_start = time.perf_counter()
        try:
            scrape_result = _trigger_scrape(execution_id)
            _log(
                session, execution_id, "scrape", "success",
                message=f"{scrape_result.get('total_insertions', 0)} insertions",
                duree_ms=int((time.perf_counter() - step_start) * 1000),
                payload=scrape_result,
            )
        except Exception as exc:  # noqa: BLE001
            _log(session, execution_id, "scrape", "error", message=str(exc))
            return {"execution_id": str(execution_id), "status": "error", "step": "scrape", "message": str(exc)}

    # --- 2. Lecture des données ---
    prix_essence, date_src_essence = _load_latest_prices(session, "carburant_essence", today)
    prix_gasoil, date_src_gasoil = _load_latest_prices(session, "carburant_gasoil", today)
    stats_essence = _load_world_stats(session, "carburant_essence")
    stats_gasoil = _load_world_stats(session, "carburant_gasoil")

    if not prix_essence and not prix_gasoil:
        msg = "Aucune donnée carburant en base."
        _log(session, execution_id, "load_data", "error", message=msg)
        return {"execution_id": str(execution_id), "status": "error", "step": "load_data", "message": msg}

    _log(
        session, execution_id, "load_data", "success",
        message=f"essence: {len(prix_essence)} pays, gasoil: {len(prix_gasoil)} pays",
    )

    # --- 3. Idempotence : article déjà publié pour ce mois ? ---
    if not force:
        month_start = today.replace(day=1)
        existing = session.scalar(
            select(ArticleGenerated)
            .where(
                ArticleGenerated.theme == "energie_carburant",
                ArticleGenerated.date_publication >= month_start,
                ArticleGenerated.langue == "fr",
            )
            .limit(1)
        )
        if existing:
            msg = f"Article carburant du mois déjà publié (id={existing.id})."
            _log(session, execution_id, "skip_already_published", "success", message=msg)
            return {
                "execution_id": str(execution_id),
                "status": "skipped",
                "reason": "already_published",
                "existing_article_id": existing.id,
            }

    # --- 4. Récupération du taux USD/TND utilisé ---
    taux_usd_tnd = None
    if prix_essence:
        # Recherche dans la première ligne avec un prix TND
        for p in prix_essence:
            if p.get("prix_tnd") and p.get("prix_usd"):
                taux_usd_tnd = round(p["prix_tnd"] / p["prix_usd"], 4)
                break

    # --- 5. Appel Claude ---
    date_src = date_src_essence or date_src_gasoil or today
    user_msg = build_user_message(
        date_jour=today,
        prix_essence=prix_essence,
        prix_gasoil=prix_gasoil,
        stats_essence=stats_essence,
        stats_gasoil=stats_gasoil,
        taux_usd_tnd=taux_usd_tnd,
        date_donnee_source=date_src,
    )
    claude = ClaudeClient()
    try:
        parsed = claude.generate_article(
            session=session, execution_id=execution_id,
            theme="energie_carburant",
            system_prompt=ENERGY_CARBURANT_SYSTEM_PROMPT,
            user_message=user_msg,
        )
    except ClaudeJSONError as exc:
        _log(session, execution_id, "claude", "error", message=str(exc))
        return {"execution_id": str(execution_id), "status": "error", "step": "claude", "message": str(exc)}

    err = _validate_output(parsed)
    if err:
        _log(session, execution_id, "claude_validation", "error", message=err)
        return {"execution_id": str(execution_id), "status": "error", "step": "claude_validation", "message": err}

    _log(session, execution_id, "claude", "success")

    # --- 6. Anti-hallucination : pool de prix autorisés ---
    allowed_numbers: list[float] = []
    for p in prix_essence + prix_gasoil:
        if p.get("prix_usd") is not None:
            allowed_numbers.append(float(p["prix_usd"]))
        if p.get("prix_tnd") is not None:
            allowed_numbers.append(float(p["prix_tnd"]))
    for s in (stats_essence, stats_gasoil):
        if s:
            for k in ("moyenne_mondiale_usd", "rang_tunisie", "nombre_pays_classement",
                     "pays_moins_cher_prix_usd", "pays_plus_cher_prix_usd"):
                if s.get(k) is not None:
                    allowed_numbers.append(float(s[k]))
    if taux_usd_tnd:
        allowed_numbers.append(float(taux_usd_tnd))
    fake_rows = [{"_v_" + str(i): v for i, v in enumerate(allowed_numbers) if v is not None}]

    publisher = get_publisher()
    articles_summary = []
    for lang in REQUIRED_LANGS:
        article = parsed[lang]
        check = check_hallucinations(article["contenu_html"], fake_rows)
        statut = "draft" if check["status"] == "passed" else "review_required"

        pub = publisher.publish(
            langue=lang, theme="energie_carburant",
            date_publication=today, article=article,
        )
        rec = ArticleGenerated(
            execution_id=execution_id, theme="energie_carburant",
            date_publication=today, langue=lang,
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

    # --- 7. Telegram ---
    duree_total = int(time.perf_counter() - started)
    tg = TelegramClient()
    notif_ok = tg.notify_articles_generated(
        session=session, execution_id=execution_id, theme="energie_carburant",
        date_iso=today.isoformat(), articles_summary=articles_summary,
        modele=claude.model, duree_secondes=duree_total,
        statut="succès" if all(a["publish_success"] for a in articles_summary) else "partiel",
    )
    _log(session, execution_id, "telegram", "success" if notif_ok else "error")
    _log(session, execution_id, "pipeline_done", "success", duree_ms=duree_total * 1000)

    return {
        "execution_id": str(execution_id),
        "status": "success",
        "theme": "energie_carburant",
        "date_publication": today.isoformat(),
        "date_donnees_source": date_src.isoformat() if date_src else None,
        "essence_pays_count": len(prix_essence),
        "gasoil_pays_count": len(prix_gasoil),
        "duree_secondes": duree_total,
        "modele_claude": claude.model,
        "publisher": publisher.backend_name,
        "telegram_sent": notif_ok,
        "articles": articles_summary,
    }
