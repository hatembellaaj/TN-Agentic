"""
Endpoints API publics du editorial-core.
Exposés à /api/* via Nginx, documentés automatiquement par FastAPI à /api/docs.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.exchange_rates import run_exchange_rates_agent
from app.agents.saturday_billets import run_saturday_agent
from app.agents.sunday_recap import run_sunday_agent
from app.agents.weather import run_weather_agent
from app.db import get_session

router = APIRouter(prefix="/agents", tags=["agents"])


class RunRequest(BaseModel):
    execution_id: str | None = None
    trigger_scrape: bool = True
    async_mode: bool = False


class RunResponse(BaseModel):
    execution_id: str
    status: str
    message: str | None = None


@router.post("/weather/run", response_model=dict[str, Any])
def run_weather(
    background_tasks: BackgroundTasks,
    payload: RunRequest | None = None,
    session: Session = Depends(get_session),
):
    """
    Déclenche l'agent météo bout en bout.

    Workflow appelé par n8n (cron 6h00) ou manuellement via Swagger.
    Si `async_mode=true`, retourne immédiatement et exécute en tâche de fond.
    """
    payload = payload or RunRequest()
    exec_id = None
    if payload.execution_id:
        try:
            exec_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc

    if payload.async_mode:
        new_id = exec_id or uuid.uuid4()
        trigger_scrape = payload.trigger_scrape

        def _run():
            from app.db import SessionLocal

            with SessionLocal() as bg_session:
                run_weather_agent(
                    bg_session, execution_id=new_id, trigger_scrape=trigger_scrape
                )

        background_tasks.add_task(_run)
        return {
            "execution_id": str(new_id),
            "status": "scheduled",
            "message": "Pipeline lancé en arrière-plan, suivre dans /dashboard/executions.",
        }

    result = run_weather_agent(
        session, execution_id=exec_id, trigger_scrape=payload.trigger_scrape
    )
    if result.get("status") == "error":
        raise HTTPException(500, result)
    return result


class ExchangeRatesRunRequest(RunRequest):
    """Body de /agents/exchange-rates/run, étendu avec require_fresh_data."""
    require_fresh_data: bool = True


@router.post("/exchange-rates/run", response_model=dict[str, Any])
def run_exchange_rates(
    background_tasks: BackgroundTasks,
    payload: ExchangeRatesRunRequest | None = None,
    session: Session = Depends(get_session),
):
    """
    Déclenche l'agent taux de change bout en bout (Sprint 2).

    Appelé par cron horaire 08:30 → 17:30 L-V. L'agent SKIP silencieusement si
    la BCT n'a pas encore publié les taux du jour, ou si un article du jour
    existe déjà. La prochaine exécution du cron réessaiera.

    Pour FORCER une génération même sur des données vieilles (mode rattrapage
    manuel), envoyer dans le body : `{"require_fresh_data": false}`.
    """
    payload = payload or ExchangeRatesRunRequest()
    exec_id = None
    if payload.execution_id:
        try:
            exec_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc

    if payload.async_mode:
        new_id = exec_id or uuid.uuid4()
        trigger_scrape = payload.trigger_scrape
        require_fresh = payload.require_fresh_data

        def _run():
            from app.db import SessionLocal

            with SessionLocal() as bg_session:
                run_exchange_rates_agent(
                    bg_session,
                    execution_id=new_id,
                    trigger_scrape=trigger_scrape,
                    require_fresh_data=require_fresh,
                )

        background_tasks.add_task(_run)
        return {
            "execution_id": str(new_id),
            "status": "scheduled",
            "message": "Pipeline lancé en arrière-plan, suivre dans /dashboard/executions.",
        }

    result = run_exchange_rates_agent(
        session,
        execution_id=exec_id,
        trigger_scrape=payload.trigger_scrape,
        require_fresh_data=payload.require_fresh_data,
    )
    if result.get("status") == "error":
        raise HTTPException(500, result)
    return result


@router.post("/saturday/run", response_model=dict[str, Any])
def run_saturday(
    background_tasks: BackgroundTasks,
    payload: RunRequest | None = None,
    session: Session = Depends(get_session),
):
    """
    Déclenche l'agent samedi : article sur l'évolution hebdomadaire des billets
    et monnaies en circulation (Sprint 3).
    """
    payload = payload or RunRequest()
    exec_id = None
    if payload.execution_id:
        try:
            exec_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc
    result = run_saturday_agent(
        session, execution_id=exec_id, trigger_scrape=payload.trigger_scrape
    )
    if result.get("status") == "error":
        raise HTTPException(500, result)
    return result


class SundayRunRequest(RunRequest):
    """Permet de surcharger le modèle Claude (Sonnet par défaut, Opus si désiré)."""
    model_override: str | None = None


@router.post("/sunday/run", response_model=dict[str, Any])
def run_sunday(
    background_tasks: BackgroundTasks,
    payload: SundayRunRequest | None = None,
    session: Session = Depends(get_session),
):
    """
    Déclenche l'agent dimanche : grand récapitulatif économique hebdomadaire
    (Sprint 3). Peut basculer sur Opus via `model_override`.
    """
    payload = payload or SundayRunRequest()
    exec_id = None
    if payload.execution_id:
        try:
            exec_id = uuid.UUID(payload.execution_id)
        except ValueError as exc:
            raise HTTPException(400, "execution_id doit être un UUID") from exc
    result = run_sunday_agent(
        session,
        execution_id=exec_id,
        trigger_scrape=payload.trigger_scrape,
        model_override=payload.model_override,
    )
    if result.get("status") == "error":
        raise HTTPException(500, result)
    return result
