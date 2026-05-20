"""
Agent dimanche : grand récapitulatif économique hebdomadaire.
Exploite TOUS les indicateurs (index.jsp + indicateurs.jsp) accumulés sur la semaine.
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
from app.prompts.sunday_recap import (
    REQUIRED_FIELDS, REQUIRED_LANGS, SUNDAY_SYSTEM_PROMPT, build_user_message,
)
from app.publishers import get_publisher
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


# Modèle Claude par défaut pour le récap dimanche (Sonnet, conformément au §6.5.6).
# Possibilité de basculer vers Opus via .env si la qualité analytique de Sonnet
# s'avère insuffisante après tests.
SUNDAY_DEFAULT_MODEL = settings.CLAUDE_MODEL_DEFAULT


# Indicateurs à inclure dans le récap dimanche (avec leur libellé éditorial)
INDICATORS_TO_INCLUDE = [
    "TMM", "TM", "taux_directeur", "TRE",
    "avoirs_nets_mdt", "avoirs_nets_jours_import",
    "billets_circulation",
    "compte_tresor",
    "refinancement",
    # depuis indicateurs.jsp
    "solde_banques",
    "bons_tresor",
    "recettes_touristiques",
    "revenus_travail_diaspora",
    "service_dette_exterieure",
    "indice_tunindex",
]


def _log(session, exec_id, step, status, message=None, duree_ms=None, payload=None):
    session.add(ExecutionLog(
        execution_id=exec_id, agent_name="sunday_recap", agent_step=step,
        status=status, message=message, duree_ms=duree_ms, payload_json=payload,
    ))
    session.commit()


def _trigger_scrape_all(execution_id: uuid.UUID) -> dict[str, Any]:
    url = f"{settings.SCRAPER_BCT_URL.rstrip('/')}/collect-all"
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, json={"execution_id": str(execution_id)})
        r.raise_for_status()
        return r.json()


def _latest_value(session: Session, ind_type: str) -> BctMacroIndicator | None:
    return session.scalar(
        select(BctMacroIndicator)
        .where(BctMacroIndicator.indicateur_type == ind_type)
        .order_by(desc(BctMacroIndicator.date_cotation), desc(BctMacroIndicator.id))
    )


def _value_at_or_before(session: Session, ind_type: str, target: dt.date) -> BctMacroIndicator | None:
    return session.scalar(
        select(BctMacroIndicator)
        .where(
            BctMacroIndicator.indicateur_type == ind_type,
            BctMacroIndicator.date_cotation <= target,
        )
        .order_by(desc(BctMacroIndicator.date_cotation), desc(BctMacroIndicator.id))
    )


def _load_indicators_complete(session: Session, today: dt.date) -> dict[str, Any]:
    """Pour chaque indicateur, valeur actuelle + valeur il y a 7 jours."""
    result: dict[str, Any] = {}
    target_j7 = today - dt.timedelta(days=7)
    for ind_type in INDICATORS_TO_INCLUDE:
        current = _latest_value(session, ind_type)
        if not current:
            continue
        block: dict[str, Any] = {
            "valeur_actuelle": float(current.valeur),
            "unite": current.unite,
            "date": current.date_cotation.isoformat() if current.date_cotation else None,
        }
        past = _value_at_or_before(session, ind_type, target_j7)
        if past and past.id != current.id and past.valeur != 0:
            delta = current.valeur - past.valeur
            pct = (delta / past.valeur) * 100
            block["variation_j7"] = {
                "valeur_il_y_a_7j": float(past.valeur),
                "date_reference": past.date_cotation.isoformat() if past.date_cotation else None,
                "delta": float(delta.quantize(Decimal("0.0001"))),
                "pourcentage": float(pct.quantize(Decimal("0.01"))),
            }
        else:
            block["variation_j7"] = None
        result[ind_type] = block
    return result


def _load_devises_today(session: Session, today: dt.date) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Renvoie (devises_actuelles, variations_j7_par_devise)."""
    rows = session.scalars(
        select(ExchangeRate)
        .where(ExchangeRate.date_cotation >= today - dt.timedelta(days=3))
        .order_by(desc(ExchangeRate.date_cotation))
    ).all()
    if not rows:
        return [], {}

    latest_date = max(r.date_cotation for r in rows)
    today_rates = [r for r in rows if r.date_cotation == latest_date]

    devises = [
        {
            "code": r.devise_code,
            "taux_moyen": float(r.taux_moyen) if r.taux_moyen else None,
            "date": r.date_cotation.isoformat(),
        }
        for r in today_rates
    ]

    variations: dict[str, dict[str, Any]] = {}
    target_j7 = latest_date - dt.timedelta(days=7)
    for r in today_rates:
        if r.taux_moyen is None:
            continue
        past = session.scalar(
            select(ExchangeRate)
            .where(
                ExchangeRate.devise_code == r.devise_code,
                ExchangeRate.date_cotation <= target_j7,
            )
            .order_by(desc(ExchangeRate.date_cotation))
        )
        if past and past.taux_moyen and past.taux_moyen != 0:
            delta = r.taux_moyen - past.taux_moyen
            pct = (delta / past.taux_moyen) * 100
            variations[r.devise_code] = {
                "taux_il_y_a_7j": float(past.taux_moyen),
                "date_reference": past.date_cotation.isoformat(),
                "delta": float(delta.quantize(Decimal("0.0001"))),
                "pourcentage": float(pct.quantize(Decimal("0.01"))),
            }
    return devises, variations


def _validate_output(parsed: dict[str, Any]) -> str | None:
    for lang in REQUIRED_LANGS:
        block = parsed.get(lang)
        if not isinstance(block, dict):
            return f"Langue manquante : {lang}"
        for f in REQUIRED_FIELDS:
            if f not in block:
                return f"Champ manquant : {lang}.{f}"
    return None


def run_sunday_agent(
    session: Session,
    *,
    execution_id: uuid.UUID | None = None,
    trigger_scrape: bool = True,
    model_override: str | None = None,
) -> dict[str, Any]:
    if execution_id is None:
        execution_id = uuid.uuid4()
    started = time.perf_counter()

    # --- 1. Scrape complet ---
    if trigger_scrape:
        try:
            sc = _trigger_scrape_all(execution_id)
            _log(session, execution_id, "scrape_all",
                 "success" if sc.get("status") == "success" else "partial",
                 message=str(sc.get("status")))
        except Exception as exc:  # noqa: BLE001
            _log(session, execution_id, "scrape_all", "error", message=str(exc))
            return {"execution_id": str(execution_id), "status": "error", "step": "scrape_all", "message": str(exc)}

    today = dt.date.today()
    week_start = today - dt.timedelta(days=6)

    # --- 2. Chargement ---
    devises_today, devises_variations = _load_devises_today(session, today)
    indicateurs = _load_indicators_complete(session, today)

    if not devises_today and not indicateurs:
        msg = "Aucune donnée économique en base."
        _log(session, execution_id, "load_data", "error", message=msg)
        return {"execution_id": str(execution_id), "status": "error", "step": "load_data", "message": msg}

    _log(session, execution_id, "load_data", "success",
         message=f"{len(devises_today)} devises, {len(indicateurs)} indicateurs chargés")

    # --- 3. Claude ---
    model = model_override or SUNDAY_DEFAULT_MODEL
    user_msg = build_user_message(today, week_start, devises_today, devises_variations, indicateurs)
    claude = ClaudeClient(model=model)
    try:
        parsed = claude.generate_article(
            session=session, execution_id=execution_id, theme="recap_economique",
            system_prompt=SUNDAY_SYSTEM_PROMPT, user_message=user_msg, max_tokens=12000,
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
    allowed_numbers: list[float] = []
    for d in devises_today:
        if d.get("taux_moyen") is not None:
            allowed_numbers.append(d["taux_moyen"])
    for code, v in devises_variations.items():
        for k in ("taux_il_y_a_7j", "delta", "pourcentage"):
            if v.get(k) is not None:
                allowed_numbers.append(v[k])
    for ind_type, info in indicateurs.items():
        if info.get("valeur_actuelle") is not None:
            allowed_numbers.append(info["valeur_actuelle"])
        v7 = info.get("variation_j7")
        if v7:
            for k in ("valeur_il_y_a_7j", "delta", "pourcentage"):
                if v7.get(k) is not None:
                    allowed_numbers.append(v7[k])
    fake_rows = [{"_v_" + str(i): v for i, v in enumerate(allowed_numbers)}]

    publisher = get_publisher()
    articles_summary = []

    for lang in REQUIRED_LANGS:
        article = parsed[lang]
        check = check_hallucinations(article["contenu_html"], fake_rows)
        statut = "draft" if check["status"] == "passed" else "review_required"

        pub = publisher.publish(
            langue=lang, theme="recap_economique",
            date_publication=today, article=article,
        )
        rec = ArticleGenerated(
            execution_id=execution_id, theme="recap_economique",
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

    duree_total = int(time.perf_counter() - started)
    tg = TelegramClient()
    notif_ok = tg.notify_articles_generated(
        session=session, execution_id=execution_id, theme="recap_economique",
        date_iso=today.isoformat(), articles_summary=articles_summary,
        modele=claude.model, duree_secondes=duree_total,
        statut="succès" if all(a["publish_success"] for a in articles_summary) else "partiel",
    )
    _log(session, execution_id, "telegram", "success" if notif_ok else "error")
    _log(session, execution_id, "pipeline_done", "success", duree_ms=duree_total * 1000)

    return {
        "execution_id": str(execution_id),
        "status": "success",
        "theme": "recap_economique",
        "date_publication": today.isoformat(),
        "semaine_du": week_start.isoformat(),
        "devises_count": len(devises_today),
        "indicateurs_count": len(indicateurs),
        "duree_secondes": duree_total,
        "modele_claude": claude.model,
        "publisher": publisher.backend_name,
        "telegram_sent": notif_ok,
        "articles": articles_summary,
    }
