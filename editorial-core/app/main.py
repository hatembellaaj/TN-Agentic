"""
Point d'entrée FastAPI du editorial-core.

Routes exposées (derrière Nginx) :
- /api/*            : endpoints protégés (JWT Bearer, cookie de session ou clé API de service)
- /api/docs         : Swagger (accès réservé aux utilisateurs connectés)
- /api/auth/*       : obtention de jeton, profil, gestion des comptes
- /dashboard/login  : connexion au dashboard (public)
- /dashboard/*      : interface Jinja2 + HTMX (session requise)
- /health           : healthcheck léger (public)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api.admin import admin_router
from app.api.history_routes import router as history_router
from app.api.routes import router as api_router
from app.auth.bootstrap import ensure_initial_admin
from app.auth.deps import (
    DashboardForbidden,
    DashboardLoginRequired,
    Principal,
    require_admin,
    require_any,
    require_dashboard_user,
)
from app.auth.routes import api_router as auth_api_router
from app.auth.routes import dashboard_auth_router
from app.config import settings
from app.dashboard.routes import router as dashboard_router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_initial_admin()
    yield


app = FastAPI(
    title="TN-Agentic — editorial-core",
    description=(
        "Cœur éditorial : génération Claude bilingue, vérification anti-hallucination, "
        "publication (FilePublisher / WordPressPublisher), notifications Telegram, "
        "dashboard de validation et traçabilité.\n\n"
        "**Authentification** : cliquer sur **Authorize** et saisir identifiant / mot de passe "
        "(schéma *JWT*), ou une clé de service (`X-API-Key`). Depuis le dashboard, la session "
        "en cours est réutilisée automatiquement."
    ),
    version="1.1.0",
    # Swagger / ReDoc / OpenAPI sont servis plus bas derrière authentification
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": False},
)


# ------------------------------------------------------------------
# Gestion des erreurs d'authentification du dashboard
# ------------------------------------------------------------------
@app.exception_handler(DashboardLoginRequired)
async def _login_redirect(_request: Request, exc: DashboardLoginRequired):
    return RedirectResponse(f"/dashboard/login?next={exc.next_url}", status_code=303)


@app.exception_handler(DashboardForbidden)
async def _forbidden(_request: Request, _exc: DashboardForbidden):
    return HTMLResponse(
        "<h1>403</h1><p>Accès réservé aux administrateurs.</p><p><a href='/dashboard/'>Retour</a></p>",
        status_code=403,
    )


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith(("/api/", "/dashboard/")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# ------------------------------------------------------------------
# Routes publiques
# ------------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard/")


# ------------------------------------------------------------------
# Documentation API (réservée aux utilisateurs authentifiés)
# ------------------------------------------------------------------
@app.get("/api/openapi.json", include_in_schema=False)
def openapi_schema(_p: Principal = Depends(require_any)):
    return JSONResponse(app.openapi())


@app.get("/api/docs", include_in_schema=False)
def swagger_ui(_p: Principal = Depends(require_dashboard_user)):
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title=f"{app.title} — Swagger",
        swagger_ui_parameters=app.swagger_ui_parameters,
    )


@app.get("/api/redoc", include_in_schema=False)
def redoc_ui(_p: Principal = Depends(require_dashboard_user)):
    return get_redoc_html(openapi_url="/api/openapi.json", title=f"{app.title} — ReDoc")


# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------
app.include_router(auth_api_router, prefix="/api")
# Agents : utilisateurs humains + compte de service (n8n)
app.include_router(api_router, prefix="/api", dependencies=[Depends(require_any)])
# Admin / debug : administrateurs uniquement
app.include_router(admin_router, prefix="/api", dependencies=[Depends(require_admin)])
# Historique (lecture) : tout compte authentifié
app.include_router(history_router, prefix="/api", dependencies=[Depends(require_any)])
# Dashboard : login public, le reste derrière session
app.include_router(dashboard_auth_router)
app.include_router(dashboard_router, dependencies=[Depends(require_dashboard_user)])
