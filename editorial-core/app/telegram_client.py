"""
Client Telegram Bot API : envoi de notifications au journaliste validateur.
Format HTML (plus robuste que MarkdownV2 face aux titres avec caractères spéciaux).
Échec non bloquant pour le pipeline.
"""
from __future__ import annotations

import html
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import NotificationLog

logger = logging.getLogger(__name__)


def _e(text: str) -> str:
    """Échappe les caractères HTML pour Telegram parse_mode=HTML (<, >, &)."""
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


class TelegramClient:

    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id_raw = settings.TELEGRAM_CHAT_ID  # peut contenir une liste séparée par virgules
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _parse_chat_ids(self) -> list[str]:
        """
        Parse TELEGRAM_CHAT_ID en liste.

        Supporte trois formes :
        - "12345"                 → ["12345"]                       (un destinataire)
        - "12345,67890,11111"     → ["12345", "67890", "11111"]     (plusieurs destinataires DM)
        - "-1001234567890"        → ["-1001234567890"]              (un groupe Telegram)

        Pour un groupe Telegram, utiliser le chat_id négatif du groupe (un seul ID,
        tout le monde dans le groupe reçoit). Pour des DM multiples, séparer par virgules.
        """
        if not self.chat_id_raw:
            return []
        return [c.strip() for c in str(self.chat_id_raw).split(",") if c.strip()]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _send_to(self, chat_id: str, text: str) -> dict[str, Any]:
        """Envoi à UN destinataire. Lève en cas d'erreur HTTP."""
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            r.raise_for_status()
            return r.json()

    def _send(self, text: str) -> dict[str, Any]:
        """
        Compat : envoi vers le PREMIER chat_id configuré.
        Garde le comportement attendu par les tests existants (un seul destinataire).
        """
        ids = self._parse_chat_ids()
        if not ids:
            raise RuntimeError("Aucun TELEGRAM_CHAT_ID configuré.")
        return self._send_to(ids[0], text)

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
        # Lignes HTML : on échappe SEULEMENT le contenu utilisateur.
        # Les balises <b>, <a>, etc. sont écrites en clair.
        lines: list[str] = [
            "<b>🤖 TN Journaliste IA</b>",
            f"📅 Date : {_e(date_iso)}",
            f"📰 Thème : {_e(theme)}",
            "",
            "<b>Brouillons générés :</b>",
        ]
        for art in articles_summary:
            url = art.get("public_url") or art.get("dashboard_url") or ""
            label = "Français" if art.get("langue") == "fr" else "English"
            titre = _e(art.get("titre") or "")
            if url:
                lines.append(f'• <a href="{_e(url)}">{label}</a> — {titre}')
            else:
                lines.append(f"• {label} — {titre} (lien indisponible)")

        lines.extend(
            [
                "",
                f"🧠 Modèle : {_e(modele)}",
                f"⏱ Exécution : {duree_secondes}s",
                f"✅ Statut : {_e(statut)}",
            ]
        )

        text = "\n".join(lines)
        chat_ids = self._parse_chat_ids()
        if not chat_ids:
            logger.warning("Aucun TELEGRAM_CHAT_ID configuré, notification ignorée.")
            return False

        # Envoi à chaque destinataire indépendamment. Si l'un d'eux échoue
        # (chat_id invalide, bloqué...), les autres reçoivent quand même.
        all_ok = True
        for chat_id in chat_ids:
            try:
                response = self._send_to(chat_id, text)
                session.add(
                    NotificationLog(
                        destinataire=chat_id,
                        canal="telegram",
                        statut="success",
                        message_envoye=text,
                        response_telegram_api=response,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                all_ok = False
                logger.exception("Echec envoi Telegram à %s", chat_id)
                session.add(
                    NotificationLog(
                        destinataire=chat_id,
                        canal="telegram",
                        statut="error",
                        message_envoye=text,
                        response_telegram_api={"error": str(exc)},
                    )
                )

        session.commit()
        return all_ok
