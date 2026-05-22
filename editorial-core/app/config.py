"""Configuration via variables d'environnement."""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str

    # Claude
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL_DEFAULT: str = "claude-sonnet-4-5-20250929"
    CLAUDE_MODEL_PREMIUM: str = "claude-opus-4-5"
    CLAUDE_SONNET_INPUT_PRICE: float = 3.0
    CLAUDE_SONNET_OUTPUT_PRICE: float = 15.0
    CLAUDE_OPUS_INPUT_PRICE: float = 15.0
    CLAUDE_OPUS_OUTPUT_PRICE: float = 75.0

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    # Publisher
    PUBLISHER_BACKEND: Literal["file", "wordpress"] = "file"
    ARTICLES_OUTPUT_DIR: str = "/var/www/articles"
    PUBLIC_BASE_URL: str = "http://localhost"

    # WordPress (utilisé si PUBLISHER_BACKEND=wordpress)
    # Auth JWT via plugin "JWT Authentication for WP REST API"
    WP_FR_BASE_URL: str = ""
    WP_FR_USERNAME: str = ""
    WP_FR_PASSWORD: str = ""
    WP_EN_BASE_URL: str = ""
    WP_EN_USERNAME: str = ""
    WP_EN_PASSWORD: str = ""
    # Champs Application Password historiques (non utilisés, conservés pour rétro-compat)
    WP_FR_APP_PASSWORD: str = ""
    WP_EN_APP_PASSWORD: str = ""

    # Scrapers internes
    SCRAPER_WEATHER_URL: str = "http://scraper-weather:8001"
    SCRAPER_BCT_URL: str = "http://scraper-bct:8002"

    LOG_LEVEL: str = "INFO"
    SERVICE_NAME: str = "editorial-core"


settings = Settings()
