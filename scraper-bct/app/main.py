"""
Service FastAPI scraper-bct : expose /collect appelé par n8n.
"""
import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.collector import collect_all_bct, collect_bct, collect_bct_indicators_detail
from app.config import settings
from app.db import get_session

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="TN-Agentic — scraper-bct",
    description=(
        "Collecte cours de devises (7) et indicateurs macro (TM, TMM, taux directeur, "
        "compte Trésor, avoirs nets MDT + jours d'importation, billets, refinancement) "
        "depuis https://www.bct.gov.tn/bct/siteprod/index.jsp."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    root_path="/scraper-bct",
)


class CollectRequest(BaseModel):
    execution_id: str | None = None


class CollectResponse(BaseModel):
    execution_id: str
    date_cotation: str | None
    devises_collectees: int
    indicateurs_collectes: int
    fiabilite_globale: str
    duree_ms: int
    status: str


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.post("/collect", response_model=CollectResponse, tags=["bct"])
def collect(
    payload: CollectRequest | None = None,
    session: Session = Depends(get_session),
) -> CollectResponse:
    """Déclenche la collecte BCT (devises + indicateurs)."""
    execution_id = None
    if payload and payload.execution_id:
        try:
            execution_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc

    result = collect_bct(session, execution_id=execution_id)
    return CollectResponse(**result)


@app.post("/collect-indicators", response_model=dict, tags=["bct"])
def collect_indicators(
    payload: CollectRequest | None = None,
    session: Session = Depends(get_session),
):
    """
    Collecte des 11 sections détaillées depuis indicateurs.jsp (Sprint 3).

    Ajoute des indicateurs supplémentaires : tourisme, diaspora, bourse, dette,
    bons du Trésor, etc.
    """
    execution_id = None
    if payload and payload.execution_id:
        try:
            execution_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc
    return collect_bct_indicators_detail(session, execution_id=execution_id)


@app.post("/collect-all", response_model=dict, tags=["bct"])
def collect_all(
    payload: CollectRequest | None = None,
    session: Session = Depends(get_session),
):
    """
    Pipeline complet : index.jsp + indicateurs.jsp en un seul appel.

    Utilisé par n8n pour les workflows hebdomadaires (samedi/dimanche)
    qui ont besoin de TOUS les indicateurs.
    """
    execution_id = None
    if payload and payload.execution_id:
        try:
            execution_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc
    return collect_all_bct(session, execution_id=execution_id)


@app.get("/preview", tags=["debug"])
def preview() -> dict:
    """Aperçu index.jsp SANS écrire en base."""
    from app.bct_client import BctClient
    from app.parser import parse_bct_index

    html = BctClient().fetch_index()
    parsed = parse_bct_index(html)
    return {
        "date_cotation": parsed["date_cotation"].isoformat() if parsed["date_cotation"] else None,
        "devises": [
            {
                "code": d["code"],
                "unite": d["unite"],
                "valeur_brute": str(d["valeur_brute"]),
                "taux_moyen_pour_1": str(d["taux_moyen_pour_1"]),
            }
            for d in parsed["devises"]
        ],
        "indicators": [
            {
                "type": i["type"],
                "valeur": str(i["valeur"]),
                "unite": i["unite"],
                "date_cotation": i["date_cotation"].isoformat() if i["date_cotation"] else None,
                "periode_str": i["periode_str"],
            }
            for i in parsed["indicators"]
        ],
    }


@app.get("/preview-indicators", tags=["debug"])
def preview_indicators() -> dict:
    """Aperçu indicateurs.jsp SANS écrire en base."""
    from app.bct_client import BctClient
    from app.parser import parse_indicators_page

    html = BctClient().fetch_indicators_page()
    rows = parse_indicators_page(html)
    return {
        "rows": [
            {
                "section_id": r["section_id"],
                "type": r["type"],
                "label": r["label"],
                "unite": r["unite"],
                "date_cotation": r["date_cotation"].isoformat() if r["date_cotation"] else None,
                "row_label": r["row_label"],
                "valeur_principale": str(r["valeur_principale"]) if r["valeur_principale"] is not None else None,
                "valeurs_brutes": r["valeurs_brutes"],
            }
            for r in rows
        ]
    }
