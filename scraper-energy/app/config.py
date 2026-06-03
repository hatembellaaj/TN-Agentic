"""Configuration scraper-energy."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str

    # GlobalPetrolPrices : domaine www (le sous-domaine fr.* renvoie 404)
    GPP_BASE_URL: str = "https://www.globalpetrolprices.com"
    GPP_USER_AGENT: str = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
    )

    LOG_LEVEL: str = "INFO"
    SERVICE_NAME: str = "scraper-energy"


settings = Settings()
