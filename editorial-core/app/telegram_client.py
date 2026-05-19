"""
Client Telegram Bot API : envoi de notifications au journaliste validateur.
Échec non bloquant pour le pipeline.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import NotificationLog

logger = logging.getLogger(__name__)


def _escape_md_v2(text: str) -> str:
    """Échappe les caractères réservés Telegram MarkdownV2."""
    specials = r"_*[]()~`>#+-=|{}.!"
    return "".join("\\" + c if c in specials else c for c in text)


class TelegramClient:

    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _send(self, text: str) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
            )
            r.raise_for_status()
            return r.json()

    def notify_articles_generated(
        self,
        session: Session,
        execution_id: uuid.UUID,
        theme: str,
        date_iso: str,
        articles_summary: list[dict[str, Any]],
        modele: str,
        duree_secondes: int,
        statut: str,
    ) -> bool:
        """
        Envoie un message Telegram listant les brouillons.

        articles_summary : [{"langue": "fr", "public_url": "...", "titre": "..."}, ...]
        Renvoie True si succès.
        """
        # Construction du message MarkdownV2
        lines = [
            "*🤖 TN Journaliste IA*",
            f"📅 Date : {_escape_md_v2(date_iso)}",
            f"📰 Thème : {_escape_md_v2(theme)}",
            "",
            "*Brouillons générés :*",
        ]
        for art in articles_summary:
            url = art.get("public_url") or art.get("dashboard_url") or "(lien indisponible)"
            label = "Français" if art["langue"] == "fr" else "English"
            lines.append(f"• [{label}]({url})")

        lines.extend(
            [
                "",
                f"🧠 Modèle : {_escape_md_v2(modele)}",
                f"⏱ Exécution : {duree_secondes}s",
                f"✅ Statut : {_escape_md_v2(statut)}",
            ]
        )

        text = "\n".join(lines)

        try:
            response = self._send(text)
            session.add(
                NotificationLog(
                    destinataire=self.chat_id,
                    canal="telegram",
                    statut="success",
                    message_envoye=text,
                    response_telegram_api=response,
                )
            )
            session.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Echec envoi Telegram")
            session.add(
                NotificationLog(
                    destinataire=self.chat_id,
                    canal="telegram",
                    statut="error",
                    message_envoye=text,
                    response_telegram_api={"error": str(exc)},
                )
            )
            session.commit()
            return False
