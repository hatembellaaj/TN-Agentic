"""
Service FastAPI scraper-weather.
Expose un endpoint /collect appelé par n8n + healthcheck + Swagger.
"""
import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.collector import collect_weather
from app.config import settings
from app.db import get_session

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="TN-Agentic — scraper-weather",
    description="Collecte OpenWeatherMap pour les 24 gouvernorats tunisiens.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    root_path="/scraper",
)


class CollectResponse(BaseModel):
    execution_id: str
    date_cotation: str
    total: int
    succes: int
    erreurs: int
    taux_succes: float
    fiabilite_globale: str
    duree_ms: int


class CollectRequest(BaseModel):
    execution_id: str | None = None


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Healthcheck léger."""
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.post("/collect", response_model=CollectResponse, tags=["weather"])
async def collect(
    payload: CollectRequest | None = None,
    session: Session = Depends(get_session),
) -> CollectResponse:
    """
    Déclenche la collecte météo des 24 gouvernorats.

    Appelée par n8n à 6h00 ou manuellement via Swagger.
    """
    execution_id = None
    if payload and payload.execution_id:
        try:
            execution_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="execution_id doit être un UUID valide"
            ) from exc

    result = await collect_weather(session, execution_id=execution_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return CollectResponse(**result)
