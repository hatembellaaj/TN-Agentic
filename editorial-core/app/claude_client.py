"""
Client Anthropic Claude avec prompt caching, retries, et logging des coûts.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

from anthropic import Anthropic, APIError, APITimeoutError
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import ClaudeLog

logger = logging.getLogger(__name__)


class ClaudeJSONError(Exception):
    """Levé si la réponse Claude n'est pas un JSON parsable malgré le retry."""


def _strip_json_fences(text: str) -> str:
    """Retire les fences ```json ... ``` si Claude en a quand même produit."""
    text = text.strip()
    if text.startswith("```"):
        # Premier fence
        text = text.split("\n", 1)[1] if "\n" in text else text
        # Dernier fence
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _estimate_cost_usd(model: str, in_tokens: int, out_tokens: int) -> Decimal:
    """Estimation des coûts par modèle (prix configurés en .env)."""
    if "opus" in model.lower():
        in_price = settings.CLAUDE_OPUS_INPUT_PRICE
        out_price = settings.CLAUDE_OPUS_OUTPUT_PRICE
    else:
        in_price = settings.CLAUDE_SONNET_INPUT_PRICE
        out_price = settings.CLAUDE_SONNET_OUTPUT_PRICE
    cost = (in_tokens / 1_000_000) * in_price + (out_tokens / 1_000_000) * out_price
    return Decimal(str(round(cost, 6)))


class ClaudeClient:
    """Wrapper autour du SDK Anthropic."""

    def __init__(self, model: str | None = None):
        self.client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = model or settings.CLAUDE_MODEL_DEFAULT

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((APIError, APITimeoutError)),
        reraise=True,
    )
    def _call_api(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 8000,
    ) -> Any:
        """Appel bas niveau avec prompt caching sur le system prompt."""
        return self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

    def generate_article(
        self,
        session: Session,
        execution_id: uuid.UUID,
        theme: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 8000,
        max_json_retries: int = 1,
    ) -> dict[str, Any]:
        """
        Appelle Claude, log les coûts, et renvoie le JSON parsé.

        En cas de JSON malformé, retry une fois avec un prompt renforcé.
        """
        started_at = time.perf_counter()
        last_error: str | None = None
        attempts = 0
        current_user_message = user_message

        while attempts <= max_json_retries:
            attempts += 1
            try:
                resp = self._call_api(system_prompt, current_user_message, max_tokens)
                raw_text = resp.content[0].text if resp.content else ""
                cleaned = _strip_json_fences(raw_text)
                parsed = json.loads(cleaned)

                # Log succès
                duree_ms = int((time.perf_counter() - started_at) * 1000)
                usage = resp.usage
                tokens_input = getattr(usage, "input_tokens", 0)
                tokens_output = getattr(usage, "output_tokens", 0)
                tokens_cache_read = getattr(usage, "cache_read_input_tokens", 0)
                tokens_cache_creation = getattr(usage, "cache_creation_input_tokens", 0)
                cout = _estimate_cost_usd(self.model, tokens_input, tokens_output)

                session.add(
                    ClaudeLog(
                        execution_id=execution_id,
                        theme=theme,
                        langue=None,  # le bloc contient FR + EN
                        prompt_envoye=current_user_message[:8000],
                        reponse_recue=raw_text[:16000],
                        tokens_input=tokens_input,
                        tokens_output=tokens_output,
                        tokens_cache_read=tokens_cache_read,
                        tokens_cache_creation=tokens_cache_creation,
                        modele_utilise=self.model,
                        cout_estime_usd=cout,
                        duree_ms=duree_ms,
                        status="success",
                    )
                )
                session.commit()
                return parsed

            except json.JSONDecodeError as exc:
                last_error = f"JSONDecodeError: {exc}"
                logger.warning(
                    "JSON malformé reçu de Claude (tentative %s/%s) : %s",
                    attempts,
                    max_json_retries + 1,
                    exc,
                )
                # Pour le retry, on insiste sur le format strict
                current_user_message = (
                    user_message
                    + "\n\nRAPPEL CRITIQUE : ta réponse précédente n'était pas un JSON valide. "
                    "Renvoie UNIQUEMENT un objet JSON strict, sans markdown, sans ```, sans texte autour."
                )
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.exception("Erreur appel Claude")
                break

        # Log échec
        duree_ms = int((time.perf_counter() - started_at) * 1000)
        session.add(
            ClaudeLog(
                execution_id=execution_id,
                theme=theme,
                prompt_envoye=user_message[:8000],
                modele_utilise=self.model,
                duree_ms=duree_ms,
                status="error",
                error_message=last_error,
            )
        )
        session.commit()
        raise ClaudeJSONError(last_error or "Échec inconnu Claude")
