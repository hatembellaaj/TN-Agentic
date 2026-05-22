"""
WordPressPublisher : publication de brouillons sur WordPress via REST API.

Deux méthodes d'authentification supportées, sélectionnées via WP_AUTH_METHOD :

  • "application_password" (recommandé, défaut)
      - Auth HTTP Basic avec un Application Password généré dans WP Admin
        (Profil → Mots de passe d'application).
      - Pas besoin de plugin tiers (natif WP depuis 5.6).
      - Le mot de passe a le format "xxxx xxxx xxxx xxxx xxxx xxxx" (24 chars + 5 espaces).
      - Plus sécurisé : scope dédié à l'app, révocable indépendamment.

  • "jwt"
      - Auth via plugin "JWT Authentication for WP REST API" (Tmeister).
      - Demande POST /wp-json/jwt-auth/v1/token avec le mot de passe utilisateur réel.
      - Token mis en cache 6 jours en mémoire, ré-acquis automatiquement sur 401.

Dans les deux cas, on POST /wp-json/wp/v2/posts avec status=draft.
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
import threading
from typing import Any, Literal

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.publishers.base import Publisher, PublishResult

logger = logging.getLogger(__name__)


# ============================================================
# Cache token JWT thread-safe
# ============================================================

class _JWTTokenCache:
    DEFAULT_VALIDITY_HOURS = 24 * 6

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
            del self._store[base_url]
            return None

    def set(self, base_url: str, token: str, validity_hours: int | None = None) -> None:
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

    # ------------------------------------------------------------
    # Credentials & méthode d'auth
    # ------------------------------------------------------------

    def _credentials_for(self, langue: str) -> tuple[str, str, str]:
        if langue == "fr":
            return (
                settings.WP_FR_BASE_URL.rstrip("/"),
                settings.WP_FR_USERNAME,
                settings.WP_FR_PASSWORD,
            )
        if langue == "en":
            if settings.WP_EN_BASE_URL:
                return (
                    settings.WP_EN_BASE_URL.rstrip("/"),
                    settings.WP_EN_USERNAME,
                    settings.WP_EN_PASSWORD,
                )
            # Site EN non distinct → on retombe sur le FR
            return (
                settings.WP_FR_BASE_URL.rstrip("/"),
                settings.WP_FR_USERNAME,
                settings.WP_FR_PASSWORD,
            )
        raise ValueError(f"Langue non supportée : {langue}")

    def _auth_method(self) -> Literal["application_password", "jwt"]:
        return settings.WP_AUTH_METHOD

    # ------------------------------------------------------------
    # Construction de l'en-tête Authorization
    # ------------------------------------------------------------

    @staticmethod
    def _basic_auth_header(username: str, app_password: str) -> str:
        """
        Construit le header pour HTTP Basic Auth avec un Application Password.
        WordPress accepte les espaces du format "xxxx xxxx ..." mais on les
        normalise pour éviter les pièges d'encoding.
        """
        # Les App Passwords WP sont au format "xxxx xxxx xxxx xxxx xxxx xxxx"
        # WP tolère les espaces, mais on les laisse tels quels pour rester
        # compatible avec le format affiché.
        token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode()
        return f"Basic {token}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _request_jwt_token(self, base_url: str, username: str, password: str) -> str:
        url = f"{base_url}{self.JWT_AUTH_PATH}"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json={"username": username, "password": password})
            r.raise_for_status()
            data = r.json()
        token = data.get("token")
        if not token:
            raise RuntimeError(f"Réponse JWT sans champ 'token' : {data}")
        return token

    def _get_jwt_token(self, base_url: str, username: str, password: str) -> str:
        cached = _TOKEN_CACHE.get(base_url)
        if cached:
            return cached
        logger.info("Demande d'un nouveau token JWT pour %s", base_url)
        token = self._request_jwt_token(base_url, username, password)
        _TOKEN_CACHE.set(base_url, token)
        return token

    def _auth_header(self, base_url: str, username: str, password: str) -> str:
        method = self._auth_method()
        if method == "application_password":
            return self._basic_auth_header(username, password)
        # JWT
        token = self._get_jwt_token(base_url, username, password)
        return f"Bearer {token}"

    # ------------------------------------------------------------
    # POST de l'article
    # ------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _post_article(self, base_url: str, auth_header: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{base_url}{self.POSTS_PATH}"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            return r.json()

    # ------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------

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
                        "Renseigner WP_FR_BASE_URL/USERNAME/PASSWORD."
                    ),
                )

            method = self._auth_method()

            # 1) Construction de l'en-tête d'auth (peut échouer pour JWT seulement)
            try:
                auth_header = self._auth_header(base_url, user, password)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response else None
                msg = exc.response.text if exc.response else str(exc)
                hint = ""
                if method == "jwt" and code == 404:
                    hint = " (plugin JWT non installé ?)"
                elif code == 403:
                    hint = " (identifiants invalides ?)"
                return PublishResult(
                    success=False,
                    backend=self.backend_name,
                    error=f"Echec auth ({method}, HTTP {code}){hint} : {msg[:300]}",
                )
            except Exception as exc:  # noqa: BLE001
                return PublishResult(
                    success=False,
                    backend=self.backend_name,
                    error=f"Echec construction header auth ({method}) : {exc}",
                )

            # 2) Payload de l'article
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

            # 3) POST avec retry automatique sur 401 (token JWT expiré)
            try:
                resp = self._post_article(base_url, auth_header, payload)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response else None
                if code == 401 and method == "jwt":
                    logger.info("Token JWT rejeté (401), invalidation cache + retry")
                    _TOKEN_CACHE.invalidate(base_url)
                    auth_header = self._auth_header(base_url, user, password)
                    resp = self._post_article(base_url, auth_header, payload)
                else:
                    msg = exc.response.text if exc.response else str(exc)
                    return PublishResult(
                        success=False,
                        backend=self.backend_name,
                        error=f"Echec création post (HTTP {code}) : {msg[:300]}",
                    )

            # 4) URLs utiles pour le journaliste
            post_id = resp.get("id")
            public_link = resp.get("link")
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
                    "auth_method": method,
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
    # Test de connexion (utilisé par /api/admin/wordpress-test)
    # ------------------------------------------------------------

    @classmethod
    def test_connection(cls, langue: str = "fr") -> dict[str, Any]:
        """Test léger d'authentification, sans publier d'article."""
        instance = cls()
        method = instance._auth_method()

        try:
            base_url, user, password = instance._credentials_for(langue)
            if not (base_url and user and password):
                return {"ok": False, "error": "Credentials manquants", "auth_method": method}

            if method == "application_password":
                # On vérifie l'auth en appelant /users/me (lecture seule)
                url = f"{base_url}/wp-json/wp/v2/users/me"
                header = cls._basic_auth_header(user, password)
                with httpx.Client(timeout=20.0) as client:
                    r = client.get(url, headers={"Authorization": header})
                    if r.status_code >= 400:
                        return {
                            "ok": False,
                            "auth_method": method,
                            "http_status": r.status_code,
                            "body": r.text[:500],
                            "hint": (
                                "App Password incorrect, expiré, ou Basic Auth bloquée. "
                                "Vérifier le mot de passe d'application dans WP Admin → Profil."
                            ),
                        }
                    me = r.json()
                    return {
                        "ok": True,
                        "auth_method": method,
                        "base_url": base_url,
                        "username": user,
                        "wp_user_id": me.get("id"),
                        "wp_user_name": me.get("name"),
                        "wp_user_roles": me.get("roles"),
                    }

            # JWT
            _TOKEN_CACHE.invalidate(base_url)
            token = instance._request_jwt_token(base_url, user, password)
            _TOKEN_CACHE.set(base_url, token)
            return {
                "ok": True,
                "auth_method": method,
                "base_url": base_url,
                "username": user,
                "token_preview": token[:24] + "…",
                "token_full_length": len(token),
            }

        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response else None
            return {
                "ok": False,
                "auth_method": method,
                "http_status": code,
                "body": (exc.response.text if exc.response else "")[:500],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "auth_method": method, "error": str(exc)}
