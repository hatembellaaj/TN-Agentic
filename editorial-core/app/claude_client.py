"""
Client LLM avec retries et logging des coûts.

Deux fournisseurs, choisis par LLM_PROVIDER :
  - "anthropic" : API Claude avec prompt caching
  - "local"     : LLM local llama.cpp (service docker `llama-server`, API
                  compatible OpenAI), sortie JSON forcée

Le nom ClaudeClient et la table claude_logs sont conservés pour ne pas
toucher aux agents ni au schéma de base.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
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


def _is_complete_json(text: str) -> bool:
    """True si le texte reçu jusqu'ici est déjà un objet JSON complet."""
    try:
        json.loads(_strip_json_fences(text))
    except json.JSONDecodeError:
        return False
    return True


def _estimate_cost_usd(model: str, in_tokens: int, out_tokens: int) -> Decimal:
    """Estimation des coûts par modèle (prix configurés en .env). Local = 0."""
    if settings.LLM_PROVIDER == "local":
        return Decimal("0")
    if "opus" in model.lower():
        in_price = settings.CLAUDE_OPUS_INPUT_PRICE
        out_price = settings.CLAUDE_OPUS_OUTPUT_PRICE
    else:
        in_price = settings.CLAUDE_SONNET_INPUT_PRICE
        out_price = settings.CLAUDE_SONNET_OUTPUT_PRICE
    cost = (in_tokens / 1_000_000) * in_price + (out_tokens / 1_000_000) * out_price
    return Decimal(str(round(cost, 6)))


class ClaudeClient:
    """Wrapper LLM : SDK Anthropic ou llama.cpp local selon LLM_PROVIDER."""

    def __init__(self, model: str | None = None):
        self.provider = settings.LLM_PROVIDER
        if self.provider == "local":
            # llama-server ne sert qu'un modèle : tout override (ex. "claude-opus-4-5"
            # du workflow n8n du dimanche) est ignoré.
            self.model = settings.LOCAL_LLM_MODEL
            self.client = None
        else:
            self.client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = model or settings.CLAUDE_MODEL_DEFAULT

    def _call_api(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 8000,
    ) -> tuple[str, dict[str, int]]:
        """Renvoie (texte brut, usage) quel que soit le fournisseur."""
        if self.provider == "local":
            return self._call_local(system_prompt, user_message, max_tokens)
        return self._call_anthropic(system_prompt, user_message, max_tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((APIError, APITimeoutError)),
        reraise=True,
    )
    def _call_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> tuple[str, dict[str, int]]:
        """Appel bas niveau avec prompt caching sur le system prompt."""
        resp = self.client.messages.create(
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
        usage = resp.usage
        return (
            resp.content[0].text if resp.content else "",
            {
                "input": getattr(usage, "input_tokens", 0),
                "output": getattr(usage, "output_tokens", 0),
                "cache_read": getattr(usage, "cache_read_input_tokens", 0),
                "cache_creation": getattr(usage, "cache_creation_input_tokens", 0),
            },
        )

    # Pas de retry sur timeout : une génération CPU qui expire ne réussira pas
    # mieux en recommençant. On retente seulement si llama-server est injoignable
    # (redémarrage, chargement du modèle) ou renvoie une erreur HTTP.
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.HTTPStatusError)),
        reraise=True,
    )
    def _call_local(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> tuple[str, dict[str, int]]:
        """
        Appel /v1/chat/completions de llama-server en streaming, sortie JSON forcée.

        Le streaming permet de journaliser l'avancement, de ne couper que si le
        serveur ne produit plus rien (LOCAL_LLM_READ_TIMEOUT_SECONDS) ou dépasse
        la durée totale (LOCAL_LLM_TIMEOUT_SECONDS), et d'arrêter si le modèle
        continue après un objet JSON complet.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "temperature": settings.LOCAL_LLM_TEMPERATURE,
        }
        # read = silence max entre deux morceaux (lecture du prompt avant le
        # premier token comprise)
        timeout = httpx.Timeout(
            connect=10.0, read=settings.LOCAL_LLM_READ_TIMEOUT_SECONDS, write=60.0, pool=10.0
        )
        started = time.monotonic()
        deadline = started + settings.LOCAL_LLM_TIMEOUT_SECONDS
        first_token_at: float | None = None
        last_progress = started
        parts: list[str] = []
        chunks = 0
        json_done_at: int | None = None
        finish_reason: str | None = None
        usage: dict[str, Any] = {}

        with httpx.stream(
            "POST",
            f"{settings.LOCAL_LLM_BASE_URL}/v1/chat/completions",
            json=payload,
            timeout=timeout,
        ) as resp:
            if resp.is_error:
                resp.read()
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                data = json.loads(data_str)
                if data.get("error"):
                    raise RuntimeError(f"llama-server : {data['error']}")
                if data.get("usage"):
                    usage = data["usage"]
                choice = (data.get("choices") or [{}])[0]
                piece = (choice.get("delta") or {}).get("content") or ""
                finish_reason = choice.get("finish_reason") or finish_reason
                now = time.monotonic()
                if piece:
                    if first_token_at is None:
                        first_token_at = now
                        logger.info(
                            "LLM local %s : prompt traité en %.0fs, génération en cours",
                            self.model,
                            now - started,
                        )
                    parts.append(piece)
                    chunks += 1
                if now > deadline:
                    raise TimeoutError(
                        f"Génération locale > {settings.LOCAL_LLM_TIMEOUT_SECONDS:.0f}s "
                        f"({chunks} tokens produits)"
                    )
                if first_token_at is not None and now - last_progress >= 60:
                    logger.info(
                        "LLM local %s : %s tokens en %.0fs (%.1f tokens/s)",
                        self.model,
                        chunks,
                        now - started,
                        chunks / max(now - first_token_at, 1e-6),
                    )
                    last_progress = now
                # Si le modèle continue après un JSON complet (blancs sans fin),
                # on laisse 20 morceaux pour recevoir la fin du flux, puis on coupe.
                if json_done_at is None:
                    if "}" in piece and _is_complete_json("".join(parts)):
                        json_done_at = chunks
                elif chunks - json_done_at > 20:
                    logger.warning(
                        "LLM local %s : JSON complet mais génération continue, arrêt du flux",
                        self.model,
                    )
                    break

        if finish_reason == "length":
            logger.warning(
                "Réponse locale tronquée (max_tokens=%s ou contexte atteint)", max_tokens
            )
        logger.info(
            "LLM local %s : %s tokens générés en %.0fs",
            self.model,
            chunks,
            time.monotonic() - started,
        )
        return (
            "".join(parts),
            {
                "input": usage.get("prompt_tokens", 0),
                "output": usage.get("completion_tokens", chunks),
                "cache_read": 0,
                "cache_creation": 0,
            },
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
                raw_text, usage = self._call_api(system_prompt, current_user_message, max_tokens)
                cleaned = _strip_json_fences(raw_text)
                parsed = json.loads(cleaned)

                # Log succès
                duree_ms = int((time.perf_counter() - started_at) * 1000)
                tokens_input = usage["input"]
                tokens_output = usage["output"]
                tokens_cache_read = usage["cache_read"]
                tokens_cache_creation = usage["cache_creation"]
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
