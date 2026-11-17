"""Business logic service for posting operations."""

import time
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from autopost_nexus.config import Settings, get_settings
from autopost_nexus.db.models import PostModel
from autopost_nexus.db.repository import PostRepository
from autopost_nexus.db.session import check_db_health
from autopost_nexus.schemas.health import (
    DatabaseHealth,
    HealthResponse,
    PlatformConfigStatus,
)
from autopost_nexus.schemas.posting import (
    PostingCreateRequest,
    PostingResponse,
    TargetStatusResponse,
)

# Application startup timestamp for uptime calculation
START_TIME = time.time()


class PostingService:
    """Service orchestrating post persistence, validation, and health checks."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None):
        self.session = session
        self.repo = PostRepository(session)
        self.settings = settings or get_settings()

    async def create_posting(self, req: PostingCreateRequest) -> tuple[PostingResponse, bool]:
        """Create a new post or return existing if idempotency key matches.

        Returns:
            Tuple[PostingResponse, bool]: (response_data, is_replay)
        """
        # 1. Idempotency Check
        if req.idempotency_key:
            existing = await self.repo.get_by_idempotency_key(req.idempotency_key)
            if existing:
                return self._to_response(existing), True

        # 2. Persist post and platform targets
        post = await self.repo.create_post(req)
        await self.session.commit()
        await self.session.refresh(post, attribute_names=["targets"])

        return self._to_response(post), False

    async def get_health_status(self) -> HealthResponse:
        """Run system and platform diagnostic checks."""
        connected, dialect, latency_ms, error = await check_db_health()
        uptime = round(time.time() - START_TIME, 2)

        # Platform configuration matrix
        platforms: dict[str, PlatformConfigStatus] = {
            "twitter": PlatformConfigStatus(
                configured=bool(
                    self.settings.TWITTER_API_KEY and self.settings.TWITTER_ACCESS_TOKEN
                ),
                auth_mode="OAuth 1.0a / Bearer v2",
                status="ready" if self.settings.TWITTER_API_KEY else "unconfigured",
            ),
            "linkedin": PlatformConfigStatus(
                configured=bool(self.settings.LINKEDIN_ACCESS_TOKEN),
                auth_mode="OAuth 2.0 Bearer",
                status="ready" if self.settings.LINKEDIN_ACCESS_TOKEN else "unconfigured",
            ),
            "telegram": PlatformConfigStatus(
                configured=bool(
                    self.settings.TELEGRAM_BOT_TOKEN and self.settings.TELEGRAM_CHAT_ID
                ),
                auth_mode="Bot Token",
                status="ready" if self.settings.TELEGRAM_BOT_TOKEN else "unconfigured",
            ),
            "discord": PlatformConfigStatus(
                configured=bool(self.settings.DISCORD_WEBHOOK_URL),
                auth_mode="Webhook URL",
                status="ready" if self.settings.DISCORD_WEBHOOK_URL else "unconfigured",
            ),
            "reddit": PlatformConfigStatus(
                configured=bool(
                    self.settings.REDDIT_CLIENT_ID and self.settings.REDDIT_CLIENT_SECRET
                ),
                auth_mode="OAuth 2.0 Password Grant",
                status="ready" if self.settings.REDDIT_CLIENT_ID else "unconfigured",
            ),
            "bluesky": PlatformConfigStatus(
                configured=bool(
                    self.settings.BLUESKY_HANDLE and self.settings.BLUESKY_APP_PASSWORD
                ),
                auth_mode="AT Protocol XRPC (App Password)",
                status="ready" if self.settings.BLUESKY_HANDLE else "unconfigured",
            ),
        }

        # Overall health assessment
        overall_status = "healthy" if connected else "unhealthy"

        return HealthResponse(
            status=overall_status,
            version=self.settings.VERSION,
            environment=self.settings.ENVIRONMENT,
            timestamp=datetime.now(UTC),
            uptime_seconds=uptime,
            database=DatabaseHealth(
                connected=connected,
                dialect=dialect,
                latency_ms=latency_ms,
                error=error,
            ),
            platforms=platforms,
        )

    def _to_response(self, post: PostModel) -> PostingResponse:
        """Map SQLAlchemy model to Pydantic response."""
        targets_resp = [
            TargetStatusResponse(
                id=t.id,
                platform=t.platform,
                status=t.status,
                external_post_id=t.external_post_id,
                external_url=t.external_url,
                retry_count=t.retry_count,
                error_message=t.error_message,
                published_at=t.published_at,
            )
            for t in post.targets
        ]

        return PostingResponse(
            id=post.id,
            title=post.title,
            content=post.content,
            status=post.status,
            idempotency_key=post.idempotency_key,
            scheduled_at=post.scheduled_at,
            created_at=post.created_at,
            updated_at=post.updated_at,
            targets=targets_resp,
        )
