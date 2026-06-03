"""Client HTTP pour GlobalPetrolPrices (domaine www uniquement)."""
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class GPPClient:
    """Wrapper minimaliste : GET avec User-Agent réaliste et retries."""

    def __init__(self) -> None:
        self.base = settings.GPP_BASE_URL
        self.headers = {
            "User-Agent": settings.GPP_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def fetch(self, path: str) -> str:
        """Récupère une page de GPP (chemin commençant par /). Renvoie le HTML."""
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base}{path}"
        with httpx.Client(timeout=30.0, follow_redirects=True, headers=self.headers) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.text
