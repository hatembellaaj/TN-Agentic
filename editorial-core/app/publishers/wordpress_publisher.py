"""
WordPressPublisher : publication des brouillons via JWT Auth + REST API.

Flux d'authentification :
1. POST /wp-json/jwt-auth/v1/token avec {username, password} → reçoit un token
2. POST /wp-json/wp/v2/posts avec header `Authorization: Bearer <token>`

Le token est mis en cache en mémoire par site (URL). Si un 401 survient, le
cache est invalidé et l'agent ré-authentifie une fois.

Pré-requis côté WordPress :
- Plugin "JWT Authentication for WP REST API" installé et activé
  (https://wordpress.org/plugins/jwt-authentication-for-wp-rest-api/)
- Constante JWT_AUTH_SECRET_KEY définie dans wp-config.php
- Constante JWT_AUTH_CORS_ENABLE = true si appels cross-origin
- L'utilisateur doit avoir le rôle 'editor' ou 'administrator' pour pouvoir
  créer des posts en draft.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.publishers.base import Publisher, PublishResult

logger = logging.getLogger(__name__)


# ============================================================
# Cache token JWT thread-safe (partagé par toutes les instances WordPressPublisher)
# ============================================================

class _JWTTokenCache:
    """
    Cache en mémoire (process-local) : {base_url: (token, expires_at_utc)}.
    Le plugin JWT WP a une validité par défaut de 7 jours, on prend 6 jours
    pour avoir une marge avant l'expiration réelle.
    """

    DEFAULT_VALIDITY_HOURS = 24 * 6  # 6 jours

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, dt.datetime]] = {}
        self._lock = threading.Lock()

    def get(self, base_url: str) -> str | None:
        with self._lock:
            entry = self._store.get(base_url)
            if entry is None:
                return None
            token, expires_at = entry
            if dt.datetime.now(dt.timezone.utc) < expires_at:
                return token
            # Expiré localement → on purge
            del self._store[base_url]
            return None

    def set(
        self, base_url: str, token: str, validity_hours: int | None = None
    ) -> None:
        hours = validity_hours or self.DEFAULT_VALIDITY_HOURS
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
        with self._lock:
            self._store[base_url] = (token, expires_at)

    def invalidate(self, base_url: str) -> None:
        with self._lock:
            self._store.pop(base_url, None)


_TOKEN_CACHE = _JWTTokenCache()


# ============================================================
# Publisher
# ============================================================

class WordPressPublisher(Publisher):
    backend_name = "wordpress"

    JWT_AUTH_PATH = "/wp-json/jwt-auth/v1/token"
    POSTS_PATH = "/wp-json/wp/v2/posts"

    def _credentials_for(self, langue: str) -> tuple[str, str, str]:
        """
        Renvoie (base_url, username, password) pour la langue donnée.
        Pour le POC, FR et EN peuvent partager la même instance WordPress si
        WP_EN_BASE_URL est vide → on retombe sur les credentials FR.
        """
        if langue == "fr":
            return (
                settings.WP_FR_BASE_URL.rstrip("/"),
                settings.WP_FR_USERNAME,
                settings.WP_FR_PASSWORD,
            )
        if langue == "en":
            # Fallback : si pas de site EN dédié, on publie sur le site FR.
            if settings.WP_EN_BASE_URL:
                return (
                    settings.WP_EN_BASE_URL.rstrip("/"),
                    settings.WP_EN_USERNAME,
                    settings.WP_EN_PASSWORD,
                )
            return (
                settings.WP_FR_BASE_URL.rstrip("/"),
                settings.WP_FR_USERNAME,
                settings.WP_FR_PASSWORD,
            )
        raise ValueError(f"Langue non supportée : {langue}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _authenticate(self, base_url: str, username: str, password: str) -> str:
        """POST /wp-json/jwt-auth/v1/token → renvoie le JWT."""
        url = f"{base_url}{self.JWT_AUTH_PATH}"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json={"username": username, "password": password})
            r.raise_for_status()
            data = r.json()

        token = data.get("token")
        if not token:
            raise RuntimeError(f"Réponse JWT inattendue (pas de token) : {data}")
        return token

    def _get_token(self, base_url: str, username: str, password: str) -> str:
        cached = _TOKEN_CACHE.get(base_url)
        if cached:
            return cached
        logger.info("Demande d'un nouveau token JWT pour %s", base_url)
        token = self._authenticate(base_url, username, password)
        _TOKEN_CACHE.set(base_url, token)
        return token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _post_article(self, base_url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{base_url}{self.POSTS_PATH}"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
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
            base_url, user, password = self._credentials_for(langue)
            if not (base_url and user and password):
                return PublishResult(
                    success=False,
                    backend=self.backend_name,
                    error=(
                        f"Credentials WordPress manquants pour la langue {langue}. "
                        "Renseigner WP_FR_BASE_URL/USERNAME/PASSWORD (et WP_EN_* si "
                        "site anglais distinct)."
                    ),
                )

            # 1) Token JWT (avec cache)
            try:
                token = self._get_token(base_url, user, password)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response else None
                msg = exc.response.text if exc.response else str(exc)
                hint = ""
                if code == 404:
                    hint = " (plugin 'JWT Authentication for WP REST API' non installé ou pas activé ?)"
                elif code == 403:
                    hint = " (identifiants invalides ?)"
                return PublishResult(
                    success=False,
                    backend=self.backend_name,
                    error=f"Echec authentification JWT (HTTP {code}){hint} : {msg[:300]}",
                )
            except Exception as exc:  # noqa: BLE001
                return PublishResult(
                    success=False,
                    backend=self.backend_name,
                    error=f"Echec authentification JWT : {exc}",
                )

            # 2) Payload pour POST /wp-json/wp/v2/posts
            payload = {
                "title": article.get("titre_editorial"),
                "content": article.get("contenu_html"),
                "excerpt": article.get("meta_description"),
                "status": "draft",  # toujours en brouillon pour validation manuelle
                "slug": article.get("slug"),
                # Métadonnées Yoast (le plugin Yoast doit accepter l'écriture via REST)
                "meta": {
                    "yoast_wpseo_title": article.get("titre_seo"),
                    "yoast_wpseo_metadesc": article.get("meta_description"),
                    "yoast_wpseo_focuskw": article.get("focus_keyword"),
                },
            }

            # 3) POST avec retry automatique en cas de token expiré (401)
            try:
                resp = self._post_article(base_url, token, payload)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response else None
                if code == 401:
                    logger.info(
                        "Token JWT WP rejeté (401), invalidation cache + re-auth"
                    )
                    _TOKEN_CACHE.invalidate(base_url)
                    token = self._get_token(base_url, user, password)
                    resp = self._post_article(base_url, token, payload)
                else:
                    msg = exc.response.text if exc.response else str(exc)
                    return PublishResult(
                        success=False,
                        backend=self.backend_name,
                        error=f"Echec création post (HTTP {code}) : {msg[:300]}",
                    )

            # 4) Réponse OK : on construit deux URLs utiles
            post_id = resp.get("id")
            public_link = resp.get("link")
            # Lien direct vers l'écran d'édition WP (le journaliste arrive sur
            # son brouillon prêt à valider et à publier)
            edit_url = f"{base_url}/wp-admin/post.php?post={post_id}&action=edit"

            return PublishResult(
                success=True,
                backend=self.backend_name,
                public_url=edit_url,
                backend_post_id=post_id,
                metadata={
                    "wp_link": public_link,
                    "wp_status": resp.get("status"),
                    "edit_url": edit_url,
                    "langue": langue,
                },
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("WordPressPublisher erreur inattendue")
            return PublishResult(
                success=False,
                backend=self.backend_name,
                error=str(exc),
            )

    # ------------------------------------------------------------
    # Helpers utilitaires
    # ------------------------------------------------------------

    @classmethod
    def test_connection(cls, langue: str = "fr") -> dict[str, Any]:
        """
        Test rapide d'authentification : essaie d'obtenir un token sans publier.
        Utilisé par l'endpoint /api/admin/wordpress-test pour valider la conf.
        """
        instance = cls()
        try:
            base_url, user, password = instance._credentials_for(langue)
            if not (base_url and user and password):
                return {"ok": False, "error": "Credentials manquants"}
            _TOKEN_CACHE.invalidate(base_url)  # force fresh
            token = instance._authenticate(base_url, user, password)
            _TOKEN_CACHE.set(base_url, token)
            return {
                "ok": True,
                "base_url": base_url,
                "username": user,
                "token_preview": token[:24] + "…",
                "token_full_length": len(token),
            }
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response else None
            return {"ok": False, "http_status": code, "body": (exc.response.text if exc.response else "")[:500]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
