"""
Point d'entrée FastAPI du editorial-core.

Routes exposées (derrière Nginx) :
- /api/*        : endpoints publics (déclenchement agents) + Swagger /api/docs
- /dashboard/*  : interface Jinja2 + HTMX de validation et de traçabilité
- /health       : healthcheck léger
"""
import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes import router as api_router
from app.config import settings
from app.dashboard.routes import router as dashboard_router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="TN-Agentic — editorial-core",
    description=(
        "Cœur éditorial : génération Claude bilingue, vérification anti-hallucination, "
        "publication (FilePublisher / WordPressPublisher), notifications Telegram, "
        "dashboard de validation et traçabilité."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME, "publisher": settings.PUBLISHER_BACKEND}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard/")


app.include_router(api_router, prefix="/api")
app.include_router(dashboard_router)
