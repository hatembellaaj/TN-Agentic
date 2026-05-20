"""Configuration via variables d'environnement."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str

    # URL du portail BCT
    BCT_INDEX_URL: str = "https://www.bct.gov.tn/bct/siteprod/index.jsp"
    # URL de la page indicateurs détaillés (11 sections : tourisme, diaspora,
    # bourse, dette extérieure, bons Trésor, etc.)
    BCT_INDICATORS_URL: str = "https://www.bct.gov.tn/bct/siteprod/indicateurs.jsp"
    BCT_USER_AGENT: str = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
    )

    LOG_LEVEL: str = "INFO"
    SERVICE_NAME: str = "scraper-bct"


settings = Settings()
