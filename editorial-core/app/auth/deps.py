"""
Dépendances FastAPI d'authentification / autorisation.

Trois façons de s'authentifier, testées dans cet ordre :
  1. En-tête ``X-API-Key``           → compte de service (n8n, scripts internes)
  2. En-tête ``Authorization: Bearer <JWT>`` → API / Swagger (bouton « Authorize »)
  3. Cookie de session ``tn_session`` (JWT HttpOnly) → dashboard, et Swagger
     ouvert depuis le dashboard (même origine)
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import TokenError, decode_access_token, match_service_api_key
from app.config import settings
from app.db import get_session
from app.models import User

SESSION_COOKIE = "tn_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/token",
    auto_error=False,
    scheme_name="JWT (login / mot de passe)",
    description="Saisir identifiant + mot de passe : Swagger récupère un JWT via /api/auth/token.",
)
api_key_scheme = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    scheme_name="Clé API de service",
    description="Clé réservée aux appels machine (n8n, cron, scripts).",
)


@dataclass(frozen=True)
class Principal:
    kind: str            # "user" | "service"
    username: str
    role: str            # "admin" | "editor" | "service"
    user_id: int | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class DashboardLoginRequired(Exception):
    def __init__(self, next_url: str) -> None:
        self.next_url = next_url


class DashboardForbidden(Exception):
    pass


def _unauthorized(detail: str = "Authentification requise") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_token(token: str, session: Session) -> User | None:
    try:
        claims = decode_access_token(token)
        user_id = int(claims["sub"])
    except (TokenError, ValueError, KeyError):
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active or user.token_version != claims.get("ver"):
        return None
    return user


def _same_origin(request: Request) -> bool:
    """Protection CSRF légère pour les requêtes authentifiées par cookie."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        # Les navigateurs modernes envoient toujours Origin sur un POST fetch/form ;
        # son absence correspond à un client non-navigateur (curl…), sans risque CSRF.
        return True
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0]
    return urlsplit(source).hostname == host


def get_principal(
    request: Request,
    bearer: str | None = Depends(oauth2_scheme),
    api_key: str | None = Depends(api_key_scheme),
    session: Session = Depends(get_session),
) -> Principal | None:
    if api_key:
        if not match_service_api_key(api_key):
            raise _unauthorized("Clé API invalide")
        principal = Principal(kind="service", username="service", role="service")
    elif bearer:
        user = _user_from_token(bearer, session)
        if user is None:
            raise _unauthorized("Jeton invalide ou expiré")
        principal = Principal("user", user.username, user.role, user.id)
    else:
        cookie = request.cookies.get(SESSION_COOKIE)
        user = _user_from_token(cookie, session) if cookie else None
        if user is None:
            return None
        if request.method not in SAFE_METHODS and not _same_origin(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Origine de la requête refusée (CSRF)")
        principal = Principal("user", user.username, user.role, user.id)

    request.state.principal = principal
    return principal


# ------------------------------------------------------------------
# API (JSON) : 401 / 403
# ------------------------------------------------------------------
def require_roles(*roles: str):
    """Exige un utilisateur authentifié ; si ``roles`` est fourni, limite aux rôles listés."""

    def _dep(principal: Principal | None = Depends(get_principal)) -> Principal:
        if principal is None:
            raise _unauthorized()
        if roles and principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Droits insuffisants")
        return principal

    return _dep


require_any = require_roles()                          # tout compte valide (y compris service)
require_human = require_roles("admin", "editor")       # utilisateurs humains uniquement
require_admin = require_roles("admin")


# ------------------------------------------------------------------
# Dashboard (HTML) : redirection vers /dashboard/login
# ------------------------------------------------------------------
def _next_url(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    return quote(path, safe="/?=&")


def require_dashboard_user(
    request: Request, principal: Principal | None = Depends(get_principal)
) -> Principal:
    if principal is None or principal.kind != "user":
        raise DashboardLoginRequired(_next_url(request))
    return principal


def require_dashboard_admin(principal: Principal = Depends(require_dashboard_user)) -> Principal:
    if not principal.is_admin:
        raise DashboardForbidden()
    return principal


def safe_next(next_url: str | None, default: str = "/dashboard/") -> str:
    """Évite les redirections ouvertes : n'accepte qu'un chemin local."""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//") or "\\" in next_url:
        return default
    return next_url


def cookie_secure() -> bool:
    return settings.COOKIE_SECURE
