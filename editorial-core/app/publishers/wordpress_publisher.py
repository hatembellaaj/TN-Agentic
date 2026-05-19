"""
WordPressPublisher : POST /wp-json/wp/v2/posts via Application Password.
Inactif tant que PUBLISHER_BACKEND != "wordpress" — préparé pour activation rapide.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.publishers.base import Publisher, PublishResult

logger = logging.getLogger(__name__)


class WordPressPublisher(Publisher):
    backend_name = "wordpress"

    def _credentials_for(self, langue: str) -> tuple[str, str, str]:
        if langue == "fr":
            return (
                settings.WP_FR_BASE_URL,
                settings.WP_FR_USERNAME,
                settings.WP_FR_APP_PASSWORD,
            )
        if langue == "en":
            return (
                settings.WP_EN_BASE_URL,
                settings.WP_EN_USERNAME,
                settings.WP_EN_APP_PASSWORD,
            )
        raise ValueError(f"Langue non supportée : {langue}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _post(self, base_url: str, auth: tuple[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json=payload, auth=auth)
            r.raise_for_status()
            return r.json()

    def publish(
        self,
        *,
        langue: str,
        theme: str,
        date_publication: dt.date,
        article: dict[str, Any],
    ) -> PublishResult:
        try:
            base_url, user, app_password = self._credentials_for(langue)
            if not (base_url and user and app_password):
                return PublishResult(
                    success=False,
                    backend=self.backend_name,
                    error=f"Credentials WordPress manquants pour la langue {langue}",
                )

            payload = {
                "title": article.get("titre_editorial"),
                "content": article.get("contenu_html"),
                "excerpt": article.get("meta_description"),
                "status": "draft",
                "slug": article.get("slug"),
                "meta": {
                    "yoast_wpseo_title": article.get("titre_seo"),
                    "yoast_wpseo_metadesc": article.get("meta_description"),
                    "yoast_wpseo_focuskw": article.get("focus_keyword"),
                },
            }

            response = self._post(base_url, (user, app_password), payload)

            return PublishResult(
                success=True,
                backend=self.backend_name,
                public_url=response.get("link"),
                backend_post_id=response.get("id"),
                metadata=response,
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("WordPressPublisher erreur")
            return PublishResult(
                success=False,
                backend=self.backend_name,
                error=str(exc),
            )
