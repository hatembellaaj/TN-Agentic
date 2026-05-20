"""Client httpx pour récupérer la page d'accueil BCT."""
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class BctClient:
    def __init__(self) -> None:
        self.url = settings.BCT_INDEX_URL
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
    def fetch_index(self) -> str:
        """Renvoie le HTML brut de la page d'accueil BCT."""
        with httpx.Client(
            timeout=30.0, follow_redirects=True, headers=self.headers
        ) as client:
            r = client.get(self.url)
            r.raise_for_status()
            # La BCT renvoie souvent du Windows-1252 ou ISO-8859-1 ;
            # httpx détecte mais on s'assure d'avoir un str décodé
            return r.text
