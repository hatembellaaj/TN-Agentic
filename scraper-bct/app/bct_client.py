"""Client httpx pour récupérer la page d'accueil BCT."""
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class BctClient:
    # Base du site BCT (pour construire les URLs relatives)
    BCT_BASE = "https://www.bct.gov.tn/bct/siteprod"
    COURS_FORM_URL = f"{BCT_BASE}/cours.jsp"
    COURS_ARCHIV_URL = f"{BCT_BASE}/cours_archiv.jsp"

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

    # ------------------------------------------------------------
    # Backfill historique via cours_archiv.jsp
    # ------------------------------------------------------------

    def open_archive_session(self) -> httpx.Client:
        """
        Ouvre un httpx.Client réutilisable pour le backfill.
        1. Fait un GET sur cours.jsp pour récupérer un JSESSIONID valide.
        2. Renvoie le client avec son cookie jar prêt à l'emploi.

        Important : à fermer avec .close() ou via `with`.
        """
        client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                **self.headers,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        # Première visite : pose le JSESSIONID dans le cookie jar
        r = client.get(self.COURS_FORM_URL)
        r.raise_for_status()
        logger.info("Session BCT ouverte (cookies : %s)", list(client.cookies.keys()))
        return client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=20),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def fetch_archive(self, client: httpx.Client, date_iso: str) -> str:
        """
        POST cours_archiv.jsp avec une date (YYYY-MM-DD).
        Le `client` DOIT venir de open_archive_session() pour avoir un cookie valide.

        Renvoie le HTML brut décodé (utilise iso-8859-1 si pas d'encoding déclaré).
        """
        r = client.post(
            self.COURS_ARCHIV_URL,
            data={"input": date_iso, "langue": ""},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": self.BCT_BASE.split("/bct/")[0],  # https://www.bct.gov.tn
                "Referer": self.COURS_FORM_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        r.raise_for_status()
        # Encoding : si la BCT n'envoie pas de charset, on prend iso-8859-1
        return r.content.decode(r.encoding or "iso-8859-1", errors="replace")
