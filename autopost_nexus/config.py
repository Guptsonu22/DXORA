"""Configuration management for AutoPost Nexus using Pydantic Settings.

Loads from environment variables or a .env file (pydantic-settings).
All credential fields are optional — missing values put that platform in
"unconfigured" state so the posting service can skip it gracefully.
"""

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

    # ===========================================================================
    # Five Required Platforms (master-prompt canonical set)
    # ===========================================================================

    # 1. Bluesky (AT Protocol) ─────────────────────────────────────────────────
    # Handle: e.g. alice.bsky.social | App Password: Settings → App Passwords
    BLUESKY_HANDLE: str | None = None
    BLUESKY_APP_PASSWORD: str | None = None
    BLUESKY_SERVICE_URL: str = "https://bsky.social"

    # 2. Mastodon (Fediverse) ─────────────────────────────────────────────────
    # Token scope required: write:statuses
    MASTODON_ACCESS_TOKEN: str | None = None
    MASTODON_INSTANCE_URL: str = "https://mastodon.social"

    # 3. DEV.to ───────────────────────────────────────────────────────────────
    # API Key: Settings → Extensions → DEV Community API Keys
    DEVTO_API_KEY: str | None = None
    DEVTO_BASE_URL: str = "https://dev.to"

    # 4. WordPress REST API ───────────────────────────────────────────────────
    # App Password: Users → Profile → Application Passwords (WP 5.6+)
    WORDPRESS_SITE_URL: str | None = None
    WORDPRESS_USERNAME: str | None = None
    WORDPRESS_APP_PASSWORD: str | None = None

    # 5. Telegram Bot API ─────────────────────────────────────────────────────
    # Bot Token: @BotFather | Channel ID: @username or -100xxxxxxxxxx
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHANNEL_ID: str | None = None
    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    # ===========================================================================
    # Legacy / Extra Platform Credentials (kept for backwards-compat with tests)
    # ===========================================================================

    TWITTER_API_KEY: str | None = None
    TWITTER_API_SECRET: str | None = None
    TWITTER_ACCESS_TOKEN: str | None = None
    TWITTER_ACCESS_SECRET: str | None = None

    LINKEDIN_ACCESS_TOKEN: str | None = None
    LINKEDIN_AUTHOR_URN: str | None = None

    DISCORD_WEBHOOK_URL: str | None = None

    REDDIT_CLIENT_ID: str | None = None
    REDDIT_CLIENT_SECRET: str | None = None
    REDDIT_USERNAME: str | None = None
    REDDIT_PASSWORD: str | None = None

    # ===========================================================================
    # Resiliency and Dispatch Limits
    # ===========================================================================

    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT_SECONDS: float = 10.0
    RATE_LIMIT_COOLDOWN_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------------------
    # Platform Configuration Helpers
    # ---------------------------------------------------------------------------

    def is_platform_configured(self, platform: str) -> bool:
        """Return True if all required credentials for the given platform are present."""
        p = platform.lower()
        if p == "bluesky":
            return bool(self.BLUESKY_HANDLE and self.BLUESKY_APP_PASSWORD)
        if p == "mastodon":
            return bool(self.MASTODON_ACCESS_TOKEN)
        if p == "devto":
            return bool(self.DEVTO_API_KEY)
        if p == "wordpress":
            return bool(
                self.WORDPRESS_SITE_URL
                and self.WORDPRESS_USERNAME
                and self.WORDPRESS_APP_PASSWORD
            )
        if p == "telegram":
            return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHANNEL_ID)
        # Legacy platforms
        if p == "twitter":
            return bool(self.TWITTER_API_KEY and self.TWITTER_ACCESS_TOKEN)
        if p == "linkedin":
            return bool(self.LINKEDIN_ACCESS_TOKEN)
        if p == "discord":
            return bool(self.DISCORD_WEBHOOK_URL)
        if p == "reddit":
            return bool(self.REDDIT_CLIENT_ID and self.REDDIT_CLIENT_SECRET)
        return False

    def get_masked_credentials(self) -> dict[str, dict[str, str | bool]]:
        """Return a non-sensitive credential summary suitable for health/telemetry endpoints."""
        from autopost_nexus.adapters.exceptions import mask_sensitive_string

        return {
            # --- Five master-prompt platforms ---
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
            "devto": {
                "configured": self.is_platform_configured("devto"),
                "api_key": mask_sensitive_string(self.DEVTO_API_KEY),
                "base_url": self.DEVTO_BASE_URL,
            },
            "wordpress": {
                "configured": self.is_platform_configured("wordpress"),
                "site_url": self.WORDPRESS_SITE_URL or "None",
                "username": self.WORDPRESS_USERNAME or "None",
                "app_password": mask_sensitive_string(self.WORDPRESS_APP_PASSWORD),
            },
            "telegram": {
                "configured": self.is_platform_configured("telegram"),
                "bot_token": mask_sensitive_string(self.TELEGRAM_BOT_TOKEN),
                "channel_id": self.TELEGRAM_CHANNEL_ID or "None",
            },
            # --- Legacy platforms ---
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
            "discord": {
                "configured": self.is_platform_configured("discord"),
                "webhook_url": mask_sensitive_string(self.DISCORD_WEBHOOK_URL),
            },
            "reddit": {
                "configured": self.is_platform_configured("reddit"),
                "client_id": mask_sensitive_string(self.REDDIT_CLIENT_ID),
                "username": self.REDDIT_USERNAME or "None",
            },
        }


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
