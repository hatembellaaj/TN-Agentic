"""
Orchestrateur de l'agent taux de change (Sprint 2).

Étapes :
1. Trigger scraper-bct.
2. Lecture des cours du jour + calcul des variations historiques.
3. Détection d'éventuelles variations notables sur les indicateurs macro.
4. Appel Claude (FR + EN).
5. Anti-hallucination.
6. Publication via Publisher.
7. Notification Telegram.
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
from app.models import ArticleGenerated, BctMacroIndicator, ExchangeRate, ExecutionLog
from app.prompts.exchange_rates import (
    EXCHANGE_RATES_SYSTEM_PROMPT,
    REQUIRED_FIELDS,
    REQUIRED_LANGS,
    build_user_message,
)
from app.publishers import get_publisher
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


# Seuils de variation au-delà desquels un indicateur macro est mentionné (cahier §5.8)
NOTABLE_THRESHOLDS = {
    "TMM": Decimal("0.1"),
    "TM": Decimal("0.1"),
    "taux_directeur": Decimal("0"),  # toute variation
    "avoirs_nets_mdt": Decimal("5"),  # en pourcentage
    "refinancement": Decimal("10"),
}


def _log_step(
    session: Session,
    execution_id: uuid.UUID,
    step: str,
    status: str,
    message: str | None = None,
    duree_ms: int | None = None,
    payload: dict | None = None,
) -> None:
    session.add(
        ExecutionLog(
            execution_id=execution_id,
            agent_name="exchange_rates",
            agent_step=step,
            status=status,
            message=message,
            duree_ms=duree_ms,
            payload_json=payload,
        )
    )
    session.commit()


def _trigger_scraper(execution_id: uuid.UUID) -> dict[str, Any]:
    url = f"{settings.SCRAPER_BCT_URL.rstrip('/')}/collect"
    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json={"execution_id": str(execution_id)})
        r.raise_for_status()
        return r.json()


def _load_today_devises(session: Session) -> tuple[list[dict[str, Any]], dt.date | None]:
    """
    Charge les cours les plus récents disponibles (1 ligne par devise).

    Fenêtre de tolérance : 14 jours. La BCT ne publie pas le week-end ni les
    jours fériés, et il peut y avoir des pannes ponctuelles. On prend toujours
    la date la plus récente disponible dans cette fenêtre, même si elle est
    de quelques jours en arrière. La date réelle est passée à Claude qui
    référence explicitement « Taux du JJ/MM/AAAA » dans l'article.
    """
    today = dt.date.today()
    rows = session.scalars(
        select(ExchangeRate)
        .where(ExchangeRate.date_cotation >= today - dt.timedelta(days=14))
        .order_by(desc(ExchangeRate.date_cotation))
    ).all()

    if not rows:
        return [], None

    # Prend la date la plus récente parmi celles disponibles
    latest_date = max(r.date_cotation for r in rows)
    selected = [r for r in rows if r.date_cotation == latest_date]

    devises = []
    for r in selected:
        raw = r.raw_data_json or {}
        devises.append(
            {
                "code": r.devise_code,
                "unite": raw.get("unite_bct"),
                "valeur_brute": raw.get("valeur_brute"),
                "taux_moyen_pour_1": float(r.taux_moyen) if r.taux_moyen is not None else None,
            }
        )
    return devises, latest_date


def _compute_variations(
    session: Session, latest_date: dt.date
) -> dict[str, dict[str, Any]]:
    """
    Pour chaque devise présente à `latest_date`, calcule la variation absolue et relative
    par rapport à J-1, J-7, J-30 (si disponible).
    """
    variations: dict[str, dict[str, Any]] = {}
    horizons = {"j1": 1, "j7": 7, "j30": 30}

    current_rates = session.scalars(
        select(ExchangeRate).where(ExchangeRate.date_cotation == latest_date)
    ).all()

    for row in current_rates:
        code = row.devise_code
        if row.taux_moyen is None:
            continue
        current = row.taux_moyen
        variations[code] = {}

        for label, days in horizons.items():
            target = latest_date - dt.timedelta(days=days)
            # Cherche le taux à la date la plus proche <= target
            past = session.scalar(
                select(ExchangeRate)
                .where(
                    ExchangeRate.devise_code == code,
                    ExchangeRate.date_cotation <= target,
                )
                .order_by(desc(ExchangeRate.date_cotation))
            )
            if past and past.taux_moyen is not None and past.taux_moyen != 0:
                delta = current - past.taux_moyen
                pct = (delta / past.taux_moyen) * 100
                variations[code][label] = {
                    "ancien": float(past.taux_moyen),
                    "ancien_date": past.date_cotation.isoformat(),
                    "delta": float(delta.quantize(Decimal("0.0001"))),
                    "pourcentage": float(pct.quantize(Decimal("0.01"))),
                }
    return variations


def _detect_notable_macro(session: Session) -> list[dict[str, Any]]:
    """
    Cherche des indicateurs macro avec variations dépassant les seuils.
    Logique simple : on compare la valeur la plus récente avec la précédente.
    """
    notables: list[dict[str, Any]] = []
    for ind_type, seuil in NOTABLE_THRESHOLDS.items():
        latest = session.scalars(
            select(BctMacroIndicator)
            .where(BctMacroIndicator.indicateur_type == ind_type)
            .order_by(desc(BctMacroIndicator.date_cotation), desc(BctMacroIndicator.id))
            .limit(2)
        ).all()
        if len(latest) < 2:
            continue
        current, previous = latest[0], latest[1]
        if previous.valeur == 0:
            continue
        delta_abs = abs(current.valeur - previous.valeur)
        delta_pct = abs((current.valeur - previous.valeur) / previous.valeur * 100)
        # Pour TMM/TM/taux_directeur on compare en absolu (points de %)
        # Pour avoirs_nets et refinancement on compare en pourcentage
        if ind_type in {"TMM", "TM", "taux_directeur"}:
            if delta_abs >= seuil:
                notables.append(
                    {
                        "type": ind_type,
                        "unite": current.unite,
                        "valeur_actuelle": float(current.valeur),
                        "valeur_precedente": float(previous.valeur),
                        "delta_absolu": float(delta_abs),
                        "date": current.date_cotation.isoformat() if current.date_cotation else None,
                    }
                )
        else:
            if delta_pct >= seuil:
                notables.append(
                    {
                        "type": ind_type,
                        "unite": current.unite,
                        "valeur_actuelle": float(current.valeur),
                        "valeur_precedente": float(previous.valeur),
                        "delta_pourcentage": float(delta_pct.quantize(Decimal("0.01"))),
                        "date": current.date_cotation.isoformat() if current.date_cotation else None,
                    }
                )
    return notables


def _validate_output(parsed: dict[str, Any]) -> str | None:
    for lang in REQUIRED_LANGS:
        block = parsed.get(lang)
        if not isinstance(block, dict):
            return f"Langue manquante ou invalide : {lang}"
        for f in REQUIRED_FIELDS:
            if f not in block:
                return f"Champ manquant : {lang}.{f}"
    return None


def run_exchange_rates_agent(
    session: Session,
    *,
    execution_id: uuid.UUID | None = None,
    trigger_scrape: bool = True,
    require_fresh_data: bool = True,
) -> dict[str, Any]:
    """
    Pipeline taux de change BCT.

    :param require_fresh_data: si True (défaut), l'agent SKIP silencieusement quand :
        - la date de la dernière cotation BCT n'est pas aujourd'hui (BCT pas encore
          publiée → on attend la prochaine exécution du cron horaire) ;
        - un article taux_change du jour est déjà en base (idempotence).
        Mettre à False pour forcer une génération manuelle même sur des données vieilles.
    """
    if execution_id is None:
        execution_id = uuid.uuid4()

    pipeline_started = time.perf_counter()

    # --- 1. Scrape ---
    if trigger_scrape:
        step_start = time.perf_counter()
        try:
            scrape_result = _trigger_scraper(execution_id)
            _log_step(
                session, execution_id, "scrape",
                "success" if scrape_result.get("status") == "success" else "error",
                message=f"{scrape_result.get('devises_collectees')} devises, "
                        f"{scrape_result.get('indicateurs_collectes')} indicateurs",
                duree_ms=int((time.perf_counter() - step_start) * 1000),
                payload=scrape_result,
            )
            if scrape_result.get("status") != "success":
                return {
                    "execution_id": str(execution_id),
                    "status": "error",
                    "step": "scrape",
                    "message": scrape_result.get("message"),
                }
        except Exception as exc:  # noqa: BLE001
            _log_step(session, execution_id, "scrape", "error", message=str(exc))
            return {"execution_id": str(execution_id), "status": "error", "step": "scrape", "message": str(exc)}

    # --- 2. Lecture devises ---
    devises, latest_date = _load_today_devises(session)
    if not devises or latest_date is None:
        msg = "Aucune cotation trouvée en base."
        _log_step(session, execution_id, "load_data", "error", message=msg)
        return {"execution_id": str(execution_id), "status": "error", "step": "load_data", "message": msg}

    _log_step(
        session, execution_id, "load_data", "success",
        message=f"{len(devises)} devises chargées (cotation du {latest_date})",
    )

    # --- 2.5 Idempotence : on a déjà publié aujourd'hui ? ---
    today = dt.date.today()
    if require_fresh_data:
        existing = session.scalar(
            select(ArticleGenerated)
            .where(
                ArticleGenerated.theme == "taux_change",
                ArticleGenerated.date_publication == today,
                ArticleGenerated.langue == "fr",  # on prend FR comme référence
            )
            .limit(1)
        )
        if existing:
            msg = f"Article taux_change du {today} déjà publié (id={existing.id}), aucune action."
            _log_step(session, execution_id, "skip_already_published", "success", message=msg)
            return {
                "execution_id": str(execution_id),
                "status": "skipped",
                "reason": "already_published",
                "existing_article_id": existing.id,
                "date_today": today.isoformat(),
            }

        # --- 2.6 Fraîcheur : la BCT a-t-elle publié aujourd'hui ? ---
        if latest_date < today:
            msg = (
                f"BCT n'a pas encore publié les taux du {today} "
                f"(dernière cotation disponible : {latest_date}). "
                "L'agent attend la prochaine exécution du cron."
            )
            _log_step(session, execution_id, "skip_stale_data", "success", message=msg)
            return {
                "execution_id": str(execution_id),
                "status": "skipped",
                "reason": "stale_data",
                "latest_bct_date": latest_date.isoformat(),
                "date_today": today.isoformat(),
                "freshness_days": (today - latest_date).days,
            }

    # --- 3. Variations ---
    variations = _compute_variations(session, latest_date)
    notables = _detect_notable_macro(session)

    # --- 4. Claude ---
    step_start = time.perf_counter()
    user_msg = build_user_message(latest_date, devises, variations=variations, indicateurs_notables=notables)
    claude = ClaudeClient()
    try:
        parsed = claude.generate_article(
            session=session,
            execution_id=execution_id,
            theme="taux_change",
            system_prompt=EXCHANGE_RATES_SYSTEM_PROMPT,
            user_message=user_msg,
        )
    except ClaudeJSONError as exc:
        _log_step(session, execution_id, "claude_generation", "error", message=str(exc))
        return {"execution_id": str(execution_id), "status": "error", "step": "claude", "message": str(exc)}

    err = _validate_output(parsed)
    if err:
        _log_step(session, execution_id, "claude_validation", "error", message=err)
        return {"execution_id": str(execution_id), "status": "error", "step": "claude_validation", "message": err}

    _log_step(
        session, execution_id, "claude_generation", "success",
        duree_ms=int((time.perf_counter() - step_start) * 1000),
    )

    # --- 5. Anti-hallucination ---
    # Pool de valeurs autorisées : taux moyens, unités, et variations calculées
    allowed_numbers: list[float] = []
    for d in devises:
        if d.get("taux_moyen_pour_1") is not None:
            allowed_numbers.append(float(d["taux_moyen_pour_1"]))
        if d.get("unite") is not None:
            allowed_numbers.append(float(d["unite"]))
        if d.get("valeur_brute") is not None:
            try:
                allowed_numbers.append(float(d["valeur_brute"]))
            except (TypeError, ValueError):
                pass
    for code, vs in variations.items():
        for label, v in vs.items():
            allowed_numbers.append(v.get("pourcentage"))
            allowed_numbers.append(v.get("delta"))
            allowed_numbers.append(v.get("ancien"))
    for n in notables:
        allowed_numbers.extend(
            [
                n.get("valeur_actuelle"),
                n.get("valeur_precedente"),
                n.get("delta_absolu"),
                n.get("delta_pourcentage"),
            ]
        )

    # Adapte le check générique au cas devises : on crée un faux "weather_row" minimal
    fake_rows = [{"_v_" + str(i): v for i, v in enumerate(allowed_numbers) if v is not None}]

    publisher = get_publisher()
    articles_summary: list[dict[str, Any]] = []

    for lang in REQUIRED_LANGS:
        article = parsed[lang]
        check = check_hallucinations(article["contenu_html"], fake_rows)
        statut_article = "draft" if check["status"] == "passed" else "review_required"

        publish_result = publisher.publish(
            langue=lang,
            theme="taux_change",
            date_publication=latest_date,
            article=article,
        )

        record = ArticleGenerated(
            execution_id=execution_id,
            theme="taux_change",
            date_publication=latest_date,
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
        session.flush()

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

    # --- 6. Telegram ---
    duree_total = int(time.perf_counter() - pipeline_started)
    telegram = TelegramClient()
    notif_ok = telegram.notify_articles_generated(
        session=session,
        execution_id=execution_id,
        theme="taux_change",
        date_iso=latest_date.isoformat(),
        articles_summary=articles_summary,
        modele=claude.model,
        duree_secondes=duree_total,
        statut="succès" if all(a["publish_success"] for a in articles_summary) else "partiel",
    )

    _log_step(session, execution_id, "telegram_notify", "success" if notif_ok else "error")
    _log_step(session, execution_id, "pipeline_done", "success", duree_ms=duree_total * 1000)

    today = dt.date.today()
    freshness_days = (today - latest_date).days
    return {
        "execution_id": str(execution_id),
        "status": "success",
        "date_cotation": latest_date.isoformat(),
        "freshness_days": freshness_days,
        "freshness_warning": (
            None if freshness_days <= 1
            else f"Données BCT vieilles de {freshness_days} jours (jour férié ou BCT non publié)."
        ),
        "duree_secondes": duree_total,
        "modele_claude": claude.model,
        "publisher": publisher.backend_name,
        "telegram_sent": notif_ok,
        "devises_count": len(devises),
        "variations_calculees": len([c for c, v in variations.items() if v]),
        "indicateurs_notables": len(notables),
        "articles": articles_summary,
    }
