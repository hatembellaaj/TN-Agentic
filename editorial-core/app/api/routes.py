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
