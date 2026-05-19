"""
Client OpenWeatherMap One Call API 3.0.
https://openweathermap.org/api/one-call-3
"""
import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class OWMClient:
    """Wrapper httpx pour One Call API 3.0."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.OPENWEATHERMAP_API_KEY
        self.base_url = base_url or settings.OPENWEATHERMAP_BASE_URL
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def fetch_one_call(
        self,
        lat: float,
        lon: float,
        units: str = "metric",
        lang: str = "fr",
        exclude: str = "minutely,alerts",
    ) -> dict[str, Any]:
        """
        Récupère météo actuelle + horaire 48h + quotidienne 8j.

        Renvoie le JSON brut de OpenWeatherMap.
        """
        params = {
            "lat": lat,
            "lon": lon,
            "units": units,
            "lang": lang,
            "exclude": exclude,
            "appid": self.api_key,
        }
        response = await self._client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()
