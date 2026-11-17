"""Configuration management for AutoPost Nexus using Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and environment configurations."""

    PROJECT_NAME: str = "AutoPost Nexus"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Database configuration
    DATABASE_URL: str = "sqlite+aiosqlite:///./autopost_nexus.db"
    DATABASE_ECHO: bool = False

    # Platform API Credentials (Optional in local/test mode)
    TWITTER_API_KEY: str | None = None
    TWITTER_API_SECRET: str | None = None
    TWITTER_ACCESS_TOKEN: str | None = None
    TWITTER_ACCESS_SECRET: str | None = None

    LINKEDIN_ACCESS_TOKEN: str | None = None
    LINKEDIN_AUTHOR_URN: str | None = None

    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    DISCORD_WEBHOOK_URL: str | None = None

    REDDIT_CLIENT_ID: str | None = None
    REDDIT_CLIENT_SECRET: str | None = None
    REDDIT_USERNAME: str | None = None
    REDDIT_PASSWORD: str | None = None

    # Resiliency and Limits
    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT_SECONDS: float = 10.0
    RATE_LIMIT_COOLDOWN_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
