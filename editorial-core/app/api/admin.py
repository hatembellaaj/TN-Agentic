"""
Endpoints admin/debug : test connexion WordPress, statut publisher, etc.
Préfixés /api/admin/ — utiles pendant la phase de POC.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.publishers import get_publisher
from app.publishers.wordpress_publisher import WordPressPublisher

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.get("/publisher-status")
def publisher_status() -> dict:
    """Renvoie le backend de publication actif et son statut basique."""
    publisher = get_publisher()
    return {
        "backend_actif": publisher.backend_name,
        "configuration": settings.PUBLISHER_BACKEND,
        "wordpress_fr_url": settings.WP_FR_BASE_URL or "(non configuré)",
        "wordpress_fr_user_set": bool(settings.WP_FR_USERNAME),
        "wordpress_fr_password_set": bool(settings.WP_FR_PASSWORD),
        "wordpress_en_url": settings.WP_EN_BASE_URL or "(même WP que FR)",
        "articles_output_dir": settings.ARTICLES_OUTPUT_DIR,
        "public_base_url": settings.PUBLIC_BASE_URL,
    }


class BackfillTriggerRequest(BaseModel):
    date_from: str
    date_to: str
    delay_min_sec: float = 3.0
    delay_max_sec: float = 6.0
    skip_weekends: bool = True


@admin_router.post("/backfill-exchange-rates")
def backfill_exchange_rates(payload: BackfillTriggerRequest) -> dict:
    """
    Proxy vers scraper-bct/backfill — déclenche le backfill historique
    via UI dashboard (un seul domaine externe).

    Attention : appel SYNCHRONE qui peut durer plusieurs minutes selon la plage
    (compte ~5 sec/jour ouvré). Pour une plage de 1 an : ~20 min. Le timeout
    httpx est mis à 7200 sec (2h) pour couvrir les gros backfills.
    """
    try:
        dt.date.fromisoformat(payload.date_from)
        dt.date.fromisoformat(payload.date_to)
    except ValueError as exc:
        raise HTTPException(400, f"Date invalide : {exc}") from exc

    url = f"{settings.SCRAPER_BCT_URL.rstrip('/')}/backfill"
    try:
        with httpx.Client(timeout=7200.0) as client:
            r = client.post(url, json=payload.model_dump())
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "http_status": exc.response.status_code,
            "body": exc.response.text[:500],
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}


@admin_router.post("/wordpress-test")
def wordpress_test(langue: Literal["fr", "en"] = "fr") -> dict:
    """
    Test rapide d'authentification JWT vers WordPress sans publier d'article.

    Utile pour vérifier la config WP_*_BASE_URL / WP_*_USERNAME / WP_*_PASSWORD
    avant de lancer un pipeline complet.

    Retourne :
      - ok=true + token preview si l'auth marche
      - ok=false + http_status + body en cas d'échec (404 = plugin JWT absent,
        403 = identifiants invalides, etc.)
    """
    return WordPressPublisher.test_connection(langue=langue)
