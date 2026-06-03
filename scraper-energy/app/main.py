"""FastAPI scraper-energy : endpoints /collect-fuel + /preview-fuel."""
import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.collector import collect_fuel
from app.config import settings
from app.db import get_session

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="TN-Agentic — scraper-energy",
    description="Collecte prix énergie depuis GlobalPetrolPrices (essence, gasoil, électricité, gaz).",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    root_path="/scraper-energy",
)


class CollectRequest(BaseModel):
    execution_id: str | None = None


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.post("/collect-fuel", tags=["energy"])
def collect_fuel_endpoint(
    payload: CollectRequest | None = None,
    session: Session = Depends(get_session),
):
    """Collecte essence + gasoil (semaine 1 du cycle énergie)."""
    execution_id = None
    if payload and payload.execution_id:
        try:
            execution_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc
    return collect_fuel(session, execution_id=execution_id)


@app.get("/preview-fuel", tags=["debug"])
def preview_fuel() -> dict:
    """Aperçu : parse les pages essence/gasoil SANS écrire en base."""
    from app.gpp_client import GPPClient
    from app.parser import parse_country_detail, parse_world_ranking

    gpp = GPPClient()
    out: dict = {}
    for label, paths in {
        "essence": {"world": "/gasoline_prices/", "tunisia": "/Tunisia/gasoline_prices/"},
        "gasoil": {"world": "/diesel_prices/", "tunisia": "/Tunisia/diesel_prices/"},
    }.items():
        try:
            html_w = gpp.fetch(paths["world"])
            world = parse_world_ranking(html_w)
        except Exception as exc:  # noqa: BLE001
            world = {"error": str(exc)}
        try:
            html_tn = gpp.fetch(paths["tunisia"])
            tn = parse_country_detail(html_tn, "Tunisia")
        except Exception as exc:  # noqa: BLE001
            tn = {"error": str(exc)}
        out[label] = {
            "world": world if isinstance(world, dict) and "error" in world else {
                "countries_count": len(world.get("countries", {})),
                "rang_tunisie": world.get("rang_tunisie"),
                "total_countries": world.get("total_countries"),
                "date_source": world.get("date_source").isoformat() if world.get("date_source") else None,
                "countries": {
                    k: {"code": v["code"], "price_usd": str(v["price_usd"])}
                    for k, v in world.get("countries", {}).items()
                },
            },
            "tunisia_detail": {
                "prix_usd": str(tn.get("prix_usd")) if tn.get("prix_usd") else None,
                "prix_local": str(tn.get("prix_local")) if tn.get("prix_local") else None,
                "devise_locale": tn.get("devise_locale"),
                "date_source": tn.get("date_source").isoformat() if tn.get("date_source") else None,
                "unite": tn.get("unite"),
            } if "error" not in tn else tn,
        }
    return out
