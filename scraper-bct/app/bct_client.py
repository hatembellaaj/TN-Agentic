"""Client httpx pour récupérer la page d'accueil BCT."""
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class BctClient:
    def __init__(self) -> None:
        self.index_url = settings.BCT_INDEX_URL
        self.indicators_url = settings.BCT_INDICATORS_URL
        self.headers = {
            "User-Agent": settings.BCT_USER_AGENT,
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _fetch(self, url: str, force_encoding: str | None = None) -> str:
        with httpx.Client(
            timeout=30.0, follow_redirects=True, headers=self.headers
        ) as client:
            r = client.get(url)
            r.raise_for_status()
            if force_encoding:
                # indicateurs.jsp est en iso-8859-1 et httpx ne le détecte pas toujours
                return r.content.decode(force_encoding, errors="replace")
            return r.text

    def fetch_index(self) -> str:
        """Renvoie le HTML de index.jsp (devises + indicateurs principaux)."""
        return self._fetch(self.index_url)

    def fetch_indicators_page(self) -> str:
        """Renvoie le HTML de indicateurs.jsp (11 sections détaillées)."""
        return self._fetch(self.indicators_url, force_encoding="iso-8859-1")
