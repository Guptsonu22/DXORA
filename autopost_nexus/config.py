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

    # Bluesky (AT Protocol) Credentials
    BLUESKY_HANDLE: str | None = None
    BLUESKY_APP_PASSWORD: str | None = None
    BLUESKY_SERVICE_URL: str = "https://bsky.social"

    # Mastodon (Fediverse) Credentials
    MASTODON_ACCESS_TOKEN: str | None = None
    MASTODON_INSTANCE_URL: str = "https://mastodon.social"

    # Resiliency and Limits
    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT_SECONDS: float = 10.0
    RATE_LIMIT_COOLDOWN_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def is_platform_configured(self, platform: str) -> bool:
        """Check whether credentials for given platform identifier are configured."""
        platform_lower = platform.lower()
        if platform_lower == "twitter":
            return bool(self.TWITTER_API_KEY and self.TWITTER_ACCESS_TOKEN)
        if platform_lower == "linkedin":
            return bool(self.LINKEDIN_ACCESS_TOKEN)
        if platform_lower == "telegram":
            return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)
        if platform_lower == "discord":
            return bool(self.DISCORD_WEBHOOK_URL)
        if platform_lower == "reddit":
            return bool(self.REDDIT_CLIENT_ID and self.REDDIT_CLIENT_SECRET)
        if platform_lower == "bluesky":
            return bool(self.BLUESKY_HANDLE and self.BLUESKY_APP_PASSWORD)
        if platform_lower == "mastodon":
            return bool(self.MASTODON_ACCESS_TOKEN)
        return False

    def get_masked_credentials(self) -> dict[str, dict[str, str | bool]]:
        """Return safe, non-sensitive credential report for telemetry."""
        from autopost_nexus.adapters.exceptions import mask_sensitive_string

        return {
            "twitter": {
                "configured": self.is_platform_configured("twitter"),
                "api_key": mask_sensitive_string(self.TWITTER_API_KEY),
                "access_token": mask_sensitive_string(self.TWITTER_ACCESS_TOKEN),
            },
            "linkedin": {
                "configured": self.is_platform_configured("linkedin"),
                "access_token": mask_sensitive_string(self.LINKEDIN_ACCESS_TOKEN),
                "author_urn": self.LINKEDIN_AUTHOR_URN or "None",
            },
            "telegram": {
                "configured": self.is_platform_configured("telegram"),
                "bot_token": mask_sensitive_string(self.TELEGRAM_BOT_TOKEN),
                "chat_id": self.TELEGRAM_CHAT_ID or "None",
            },
            "discord": {
                "configured": self.is_platform_configured("discord"),
                "webhook_url": mask_sensitive_string(self.DISCORD_WEBHOOK_URL),
            },
            "reddit": {
                "configured": self.is_platform_configured("reddit"),
                "client_id": mask_sensitive_string(self.REDDIT_CLIENT_ID),
                "username": self.REDDIT_USERNAME or "None",
            },
            "bluesky": {
                "configured": self.is_platform_configured("bluesky"),
                "handle": self.BLUESKY_HANDLE or "None",
                "app_password": mask_sensitive_string(self.BLUESKY_APP_PASSWORD),
                "service_url": self.BLUESKY_SERVICE_URL,
            },
            "mastodon": {
                "configured": self.is_platform_configured("mastodon"),
                "access_token": mask_sensitive_string(self.MASTODON_ACCESS_TOKEN),
                "instance_url": self.MASTODON_INSTANCE_URL,
            },
        }


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
