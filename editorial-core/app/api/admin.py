"""
Endpoints admin/debug : test connexion WordPress, statut publisher, etc.
Préfixés /api/admin/ — utiles pendant la phase de POC.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

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
