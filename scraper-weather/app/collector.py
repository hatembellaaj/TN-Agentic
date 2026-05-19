"""
Collecte la météo des 24 gouvernorats et persiste en base.
Logique métier découplée de FastAPI pour faciliter les tests.
"""
import asyncio
import datetime as dt
import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import ExecutionLog, Governorate, WeatherData
from app.owm_client import OWMClient

logger = logging.getLogger(__name__)


def _extract_daily_summary(owm_payload: dict[str, Any]) -> dict[str, Any]:
    """Extrait les champs météo principaux du payload OWM One Call 3.0."""
    current = owm_payload.get("current", {})
    daily = owm_payload.get("daily", [])
    today = daily[0] if daily else {}

    temp_today = today.get("temp", {})

    weather = current.get("weather", [{}])[0]

    return {
        "temperature_actuelle": current.get("temp"),
        "temperature_min": temp_today.get("min"),
        "temperature_max": temp_today.get("max"),
        "conditions": weather.get("description"),
        "humidite": current.get("humidity"),
        "vent_vitesse": current.get("wind_speed"),
        "vent_direction": current.get("wind_deg"),
        "pression": current.get("pressure"),
        "indice_uv": today.get("uvi"),
        "precipitations_mm": today.get("rain", 0.0),
        "previsions_5j_json": [
            {
                "date": dt.date.fromtimestamp(d.get("dt", 0)).isoformat(),
                "temp_min": d.get("temp", {}).get("min"),
                "temp_max": d.get("temp", {}).get("max"),
                "conditions": (d.get("weather") or [{}])[0].get("description"),
                "precipitations_mm": d.get("rain", 0.0),
            }
            for d in daily[1:6]
        ],
    }


async def _collect_one(
    client: OWMClient, gov: Governorate, execution_id: uuid.UUID
) -> tuple[Governorate, dict[str, Any] | None, str | None]:
    """Récupère la météo pour un gouvernorat. Renvoie (gov, summary, error)."""
    try:
        raw = await client.fetch_one_call(
            lat=float(gov.latitude), lon=float(gov.longitude), lang="fr"
        )
        summary = _extract_daily_summary(raw)
        summary["raw_data_json"] = raw
        return gov, summary, None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Echec collecte météo gouvernorat=%s", gov.nom_fr)
        return gov, None, str(exc)


async def collect_weather(session: Session, execution_id: uuid.UUID | None = None) -> dict[str, Any]:
    """
    Lance la collecte parallèle pour les 24 gouvernorats actifs.

    Renvoie un récapitulatif (succès / échecs / fiabilité globale).
    """
    if execution_id is None:
        execution_id = uuid.uuid4()

    today = dt.date.today()
    started_at = time.perf_counter()

    govs = session.scalars(
        select(Governorate).where(Governorate.actif == True).order_by(Governorate.ordre_affichage)  # noqa: E712
    ).all()

    if not govs:
        return {
            "execution_id": str(execution_id),
            "status": "error",
            "message": "Aucun gouvernorat actif trouvé. Le seed a-t-il été exécuté ?",
        }

    client = OWMClient()
    try:
        results = await asyncio.gather(
            *[_collect_one(client, gov, execution_id) for gov in govs]
        )
    finally:
        await client.close()

    succes = 0
    erreurs = 0

    for gov, summary, error in results:
        if summary is None:
            erreurs += 1
            continue

        # UPSERT (governorate_id, date_cotation) → respecte uq_weather_gov_date
        stmt = pg_insert(WeatherData).values(
            governorate_id=gov.id,
            date_cotation=today,
            temperature_min=summary["temperature_min"],
            temperature_max=summary["temperature_max"],
            temperature_actuelle=summary["temperature_actuelle"],
            conditions=summary["conditions"],
            humidite=summary["humidite"],
            vent_vitesse=summary["vent_vitesse"],
            vent_direction=summary["vent_direction"],
            pression=summary["pression"],
            indice_uv=summary["indice_uv"],
            precipitations_mm=summary["precipitations_mm"],
            previsions_5j_json=summary["previsions_5j_json"],
            source="openweathermap",
            fiabilite="haute",
            raw_data_json=summary["raw_data_json"],
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_weather_gov_date",
            set_={
                "temperature_min": stmt.excluded.temperature_min,
                "temperature_max": stmt.excluded.temperature_max,
                "temperature_actuelle": stmt.excluded.temperature_actuelle,
                "conditions": stmt.excluded.conditions,
                "humidite": stmt.excluded.humidite,
                "vent_vitesse": stmt.excluded.vent_vitesse,
                "vent_direction": stmt.excluded.vent_direction,
                "pression": stmt.excluded.pression,
                "indice_uv": stmt.excluded.indice_uv,
                "precipitations_mm": stmt.excluded.precipitations_mm,
                "previsions_5j_json": stmt.excluded.previsions_5j_json,
                "raw_data_json": stmt.excluded.raw_data_json,
                "timestamp_collecte": dt.datetime.now(dt.timezone.utc),
                "fiabilite": stmt.excluded.fiabilite,
            },
        )
        session.execute(stmt)
        succes += 1

    session.commit()

    total = len(govs)
    taux = (succes / total) * 100 if total else 0.0
    fiabilite_globale = (
        "haute" if taux >= 98 else "moyenne" if taux >= 90 else "basse"
    )

    duree_ms = int((time.perf_counter() - started_at) * 1000)

    # Log d'exécution
    session.add(
        ExecutionLog(
            execution_id=execution_id,
            agent_name="scraper-weather",
            agent_step="collect_weather",
            status="success" if erreurs == 0 else ("partial" if succes else "error"),
            message=f"{succes}/{total} succès ({taux:.1f}%)",
            duree_ms=duree_ms,
            payload_json={"succes": succes, "erreurs": erreurs, "total": total},
        )
    )
    session.commit()

    return {
        "execution_id": str(execution_id),
        "date_cotation": today.isoformat(),
        "total": total,
        "succes": succes,
        "erreurs": erreurs,
        "taux_succes": round(taux, 2),
        "fiabilite_globale": fiabilite_globale,
        "duree_ms": duree_ms,
    }
