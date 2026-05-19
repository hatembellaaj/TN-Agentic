"""Configuration via variables d'environnement."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str

    # OpenWeatherMap
    OPENWEATHERMAP_API_KEY: str
    OPENWEATHERMAP_BASE_URL: str = "https://api.openweathermap.org/data/3.0/onecall"

    # Logging
    LOG_LEVEL: str = "INFO"

    # Service
    SERVICE_NAME: str = "scraper-weather"


settings = Settings()
