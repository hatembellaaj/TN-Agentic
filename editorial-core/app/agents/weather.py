"""
Orchestrateur de l'agent météo (Sprint 1).

Étapes :
1. Lit weather_data du jour (peuplé par scraper-weather).
2. Construit le payload pour Claude.
3. Appel Claude (FR + EN dans un seul appel).
4. Vérification anti-hallucination.
5. Publication via Publisher (file pour POC, wordpress quand dispo).
6. Persistance en articles_generated.
7. Notification Telegram.
8. Log execution_logs.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claude_client import ClaudeClient, ClaudeJSONError
from app.config import settings
from app.hallucination_check import check_hallucinations
from app.models import ArticleGenerated, ExecutionLog, Governorate, WeatherData
from app.prompts.weather import REQUIRED_FIELDS, REQUIRED_LANGS, WEATHER_SYSTEM_PROMPT, build_user_message
from app.publishers import get_publisher
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def _log_step(
    session: Session,
    execution_id: uuid.UUID,
    step: str,
    status: str,
    message: str | None = None,
    duree_ms: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        ExecutionLog(
            execution_id=execution_id,
            agent_name="weather",
            agent_step=step,
            status=status,
            message=message,
            duree_ms=duree_ms,
            payload_json=payload,
        )
    )
    session.commit()


def _trigger_scraper(execution_id: uuid.UUID) -> dict[str, Any]:
    """Déclenche la collecte météo via scraper-weather."""
    url = f"{settings.SCRAPER_WEATHER_URL.rstrip('/')}/collect"
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, json={"execution_id": str(execution_id)})
        r.raise_for_status()
        return r.json()


def _round_int(val) -> int | None:
    """Arrondit une valeur numérique à l'entier le plus proche. None → None.

    Règle métier (mise à jour mai 2026) : pour la crédibilité éditoriale, toutes
    les températures et vitesses de vent sont arrondies à l'entier AVANT d'être
    envoyées à Claude. Ainsi le LLM ne peut pas écrire « 33,22 °C », il ne voit
    que « 33 ». La donnée brute reste stockée intacte en base (raw_data_json,
    temperature_min en Numeric(5,2)) pour les analyses futures.
    """
    if val is None:
        return None
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def _load_today_weather(session: Session) -> list[dict[str, Any]]:
    """Charge les données weather_data du jour, ordonnées par ordre d'affichage.

    Les températures et la vitesse du vent sont arrondies à l'entier (règle
    éditoriale non négociable). L'humidité et la pression sont déjà entières en
    base. L'indice UV reste en décimal (utile pour les seuils de protection),
    Claude est invité à l'approcher en mots dans le prompt système.
    """
    today = dt.date.today()
    rows = session.execute(
        select(Governorate, WeatherData)
        .join(WeatherData, WeatherData.governorate_id == Governorate.id)
        .where(WeatherData.date_cotation == today)
        .where(Governorate.actif == True)  # noqa: E712
        .order_by(Governorate.ordre_affichage)
    ).all()

    out: list[dict[str, Any]] = []
    for gov, wd in rows:
        out.append(
            {
                "ordre": gov.ordre_affichage,
                "nom_fr": gov.nom_fr,
                "nom_en": gov.nom_en or gov.nom_fr,
                "region": gov.region,
                # Températures : arrondies à l'entier (règle de crédibilité)
                "temperature_min": _round_int(wd.temperature_min),
                "temperature_max": _round_int(wd.temperature_max),
                "temperature_actuelle": _round_int(wd.temperature_actuelle),
                "conditions": wd.conditions,
                "humidite": wd.humidite,
                # Vent : arrondi à l'entier (règle de crédibilité)
                "vent_vitesse": _round_int(wd.vent_vitesse),
                "vent_direction": wd.vent_direction,
                "pression": wd.pression,
                # UV : conservé en décimal (Claude est instruit d'approximer en mots)
                "indice_uv": float(wd.indice_uv) if wd.indice_uv is not None else None,
                # Précipitations : 1 décimale (0,3 mm vs 0 mm fait une différence)
                "precipitations_mm": (
                    round(float(wd.precipitations_mm), 1)
                    if wd.precipitations_mm is not None
                    else None
                ),
            }
        )
    return out


def _validate_claude_output(parsed: dict[str, Any]) -> str | None:
    """Renvoie un message d'erreur si la structure JSON n'est pas conforme, sinon None."""
    for lang in REQUIRED_LANGS:
        block = parsed.get(lang)
        if not isinstance(block, dict):
            return f"Langue manquante ou invalide : {lang}"
        for field in REQUIRED_FIELDS:
            if field not in block:
                return f"Champ manquant : {lang}.{field}"
    return None


def run_weather_agent(
    session: Session,
    *,
    execution_id: uuid.UUID | None = None,
    trigger_scrape: bool = True,
) -> dict[str, Any]:
    """
    Point d'entrée principal. Renvoie un dict de résultat.

    :param trigger_scrape: si True, appelle scraper-weather avant ; sinon lit la base directement.
    """
    if execution_id is None:
        execution_id = uuid.uuid4()

    pipeline_started = time.perf_counter()
    today = dt.date.today()

    # ----------- 1. Collecte météo -----------
    if trigger_scrape:
        step_start = time.perf_counter()
        try:
            scrape_result = _trigger_scraper(execution_id)
            _log_step(
                session, execution_id, "scrape", "success",
                message=f"{scrape_result.get('succes')}/{scrape_result.get('total')} succès",
                duree_ms=int((time.perf_counter() - step_start) * 1000),
                payload=scrape_result,
            )
        except Exception as exc:  # noqa: BLE001
            _log_step(
                session, execution_id, "scrape", "error",
                message=str(exc),
                duree_ms=int((time.perf_counter() - step_start) * 1000),
            )
            return {
                "execution_id": str(execution_id),
                "status": "error",
                "step": "scrape",
                "message": str(exc),
            }

    # ----------- 2. Lecture des données -----------
    weather_rows = _load_today_weather(session)
    if not weather_rows:
        msg = "Aucune donnée météo trouvée en base pour aujourd'hui."
        _log_step(session, execution_id, "load_data", "error", message=msg)
        return {"execution_id": str(execution_id), "status": "error", "step": "load_data", "message": msg}

    _log_step(
        session, execution_id, "load_data", "success",
        message=f"{len(weather_rows)} gouvernorats chargés",
        payload={"count": len(weather_rows)},
    )

    # ----------- 3. Appel Claude -----------
    step_start = time.perf_counter()
    user_msg = build_user_message(today, weather_rows)
    claude = ClaudeClient()
    try:
        parsed = claude.generate_article(
            session=session,
            execution_id=execution_id,
            theme="meteo",
            system_prompt=WEATHER_SYSTEM_PROMPT,
            user_message=user_msg,
        )
    except ClaudeJSONError as exc:
        _log_step(
            session, execution_id, "claude_generation", "error",
            message=str(exc),
            duree_ms=int((time.perf_counter() - step_start) * 1000),
        )
        return {"execution_id": str(execution_id), "status": "error", "step": "claude", "message": str(exc)}

    err = _validate_claude_output(parsed)
    if err:
        _log_step(session, execution_id, "claude_validation", "error", message=err, payload=parsed)
        return {"execution_id": str(execution_id), "status": "error", "step": "claude_validation", "message": err}

    _log_step(
        session, execution_id, "claude_generation", "success",
        duree_ms=int((time.perf_counter() - step_start) * 1000),
        message="JSON FR+EN valide",
    )

    # ----------- 4. Anti-hallucination -----------
    publisher = get_publisher()
    articles_summary: list[dict[str, Any]] = []

    for lang in REQUIRED_LANGS:
        article = parsed[lang]
        check = check_hallucinations(article["contenu_html"], weather_rows)
        statut_article = "draft" if check["status"] == "passed" else "review_required"

        # ----------- 5. Publication -----------
        publish_result = publisher.publish(
            langue=lang,
            theme="meteo",
            date_publication=today,
            article=article,
        )

        # ----------- 6. Persistance article -----------
        record = ArticleGenerated(
            execution_id=execution_id,
            theme="meteo",
            date_publication=today,
            langue=lang,
            titre_editorial=article["titre_editorial"][:500],
            titre_seo=(article.get("titre_seo") or "")[:200],
            slug=(article.get("slug") or "")[:255],
            meta_description=(article.get("meta_description") or "")[:300],
            focus_keyword=(article.get("focus_keyword") or "")[:100],
            mots_cles=article.get("mots_cles_secondaires"),
            contenu_html=article["contenu_html"],
            categorie_wordpress=article.get("categorie_suggeree"),
            wordpress_post_id=publish_result.backend_post_id,
            wordpress_post_url=publish_result.public_url if publish_result.backend == "wordpress" else None,
            file_path=publish_result.file_path,
            statut=statut_article,
            hallucination_check=check["status"],
            hallucination_details=check,
            modele_claude_utilise=claude.model,
            raw_claude_response=parsed,
        )
        session.add(record)
        session.flush()  # pour récupérer l'ID

        articles_summary.append(
            {
                "id": record.id,
                "langue": lang,
                "titre": article["titre_editorial"],
                "public_url": publish_result.public_url,
                "dashboard_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/dashboard/articles/{record.id}",
                "publish_success": publish_result.success,
                "hallucination_status": check["status"],
            }
        )

    session.commit()

    _log_step(
        session, execution_id, "publish", "success",
        payload={"articles": [{"id": a["id"], "lang": a["langue"]} for a in articles_summary]},
    )

    # ----------- 7. Notification Telegram -----------
    duree_total = int(time.perf_counter() - pipeline_started)
    telegram = TelegramClient()
    notif_ok = telegram.notify_articles_generated(
        session=session,
        execution_id=execution_id,
        theme="meteo",
        date_iso=today.isoformat(),
        articles_summary=articles_summary,
        modele=claude.model,
        duree_secondes=duree_total,
        statut="succès" if all(a["publish_success"] for a in articles_summary) else "partiel",
    )

    _log_step(
        session, execution_id, "telegram_notify",
        "success" if notif_ok else "error",
    )

    _log_step(
        session, execution_id, "pipeline_done", "success",
        duree_ms=duree_total * 1000,
    )

    return {
        "execution_id": str(execution_id),
        "status": "success",
        "date_publication": today.isoformat(),
        "duree_secondes": duree_total,
        "modele_claude": claude.model,
        "publisher": publisher.backend_name,
        "telegram_sent": notif_ok,
        "articles": articles_summary,
    }
