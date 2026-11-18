"""Unified test suite for all five supported platform adapters per Master Prompt Part 3 and Part 9.

Tests:
- Bluesky (AT Protocol XRPC createSession + createRecord)
- Mastodon (OAuth 2.0 Bearer + POST /api/v1/statuses)
- DEV.to (API Key + POST /api/articles with published=true)
- WordPress (Application Password HTTP Basic + POST /wp/v2/posts with status=publish)
- Telegram (Bot API + POST /sendMessage with public/private channel handling)
- Security & credential masking across all adapters
"""

import httpx
import pytest
import respx

from autopost_nexus.adapters.bluesky import BlueskyAdapter
from autopost_nexus.adapters.devto import DevtoAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformRateLimitError,
    mask_sensitive_string,
)
from autopost_nexus.adapters.mastodon import MastodonAdapter
from autopost_nexus.adapters.schemas import PlatformPostPayload, PublishResult
from autopost_nexus.adapters.telegram import TelegramAdapter
from autopost_nexus.adapters.wordpress import WordPressAdapter
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType

# ---------------------------------------------------------------------------
# 1. Bluesky Adapter Unified Tests
# ---------------------------------------------------------------------------

class TestBlueskyUnified:
    """Mocked unit tests for Bluesky AT Protocol adapter."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_bluesky_successful_publish(self):
        settings = Settings(
            BLUESKY_IDENTIFIER="alice.bsky.social",
            BLUESKY_APP_PASSWORD="abcd-1234-efgh-5678",
        )
        adapter = BlueskyAdapter(settings=settings)

        # Mock createSession
        respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
            200,
            json={
                "accessJwt": "jwt-token-123",
                "refreshJwt": "refresh-token-456",
                "handle": "alice.bsky.social",
                "did": "did:plc:alice123",
            },
        )

        # Mock createRecord
        respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").respond(
            200,
            json={
                "uri": "at://did:plc:alice123/app.bsky.feed.post/3k123456789",
                "cid": "bafyreia123",
            },
        )

        payload = PlatformPostPayload(
            content="Check out our platform launch! https://example.com"
        )
        result = await adapter.publish(payload)

        assert isinstance(result, PublishResult)
        assert result.success is True
        assert result.platform == PlatformType.BLUESKY
        assert result.external_post_id == "at://did:plc:alice123/app.bsky.feed.post/3k123456789"
        assert result.external_url == "https://bsky.app/profile/alice.bsky.social/post/3k123456789"
        assert result.raw_response["uri"] is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_bluesky_authentication_failure(self):
        settings = Settings(
            BLUESKY_IDENTIFIER="bad.user.bsky.social",
            BLUESKY_APP_PASSWORD="wrong-password",
        )
        adapter = BlueskyAdapter(settings=settings)

        respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
            401,
            json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"},
        )

        payload = PlatformPostPayload(content="Testing auth error https://example.com")
        with pytest.raises(PlatformAuthenticationError):
            await adapter.publish(payload)

    def test_bluesky_unconfigured(self):
        settings = Settings(BLUESKY_IDENTIFIER=None, BLUESKY_APP_PASSWORD=None)
        adapter = BlueskyAdapter(settings=settings)
        assert adapter.is_configured() is False


# ---------------------------------------------------------------------------
# 2. Mastodon Adapter Unified Tests
# ---------------------------------------------------------------------------

class TestMastodonUnified:
    """Mocked unit tests for Mastodon adapter."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_mastodon_successful_publish(self):
        settings = Settings(
            MASTODON_INSTANCE_URL="https://mastodon.social",
            MASTODON_ACCESS_TOKEN="masto-token-secret-123",
        )
        adapter = MastodonAdapter(settings=settings)

        respx.post("https://mastodon.social/api/v1/statuses").respond(
            200,
            json={
                "id": "112233445566",
                "created_at": "2026-11-18T12:00:00.000Z",
                "url": "https://mastodon.social/@user/112233445566",
                "visibility": "public",
            },
        )

        payload = PlatformPostPayload(
            content="Mastodon broadcast status https://example.com"
        )
        result = await adapter.publish(payload)

        assert result.success is True
        assert result.platform == PlatformType.MASTODON
        assert result.external_post_id == "112233445566"
        assert result.external_url == "https://mastodon.social/@user/112233445566"

    @pytest.mark.asyncio
    @respx.mock
    async def test_mastodon_rate_limit_handling(self):
        settings = Settings(
            MASTODON_INSTANCE_URL="https://mastodon.social",
            MASTODON_ACCESS_TOKEN="masto-token-123",
        )
        adapter = MastodonAdapter(settings=settings)

        respx.post("https://mastodon.social/api/v1/statuses").respond(
            429,
            headers={"X-RateLimit-Reset": "2026-11-18T13:00:00Z"},
            json={"error": "Rate limit exceeded"},
        )

        payload = PlatformPostPayload(content="Testing rate limit https://example.com")
        with pytest.raises(PlatformRateLimitError):
            await adapter.publish(payload)


# ---------------------------------------------------------------------------
# 3. DEV.to Adapter Unified Tests
# ---------------------------------------------------------------------------

class TestDevtoUnified:
    """Mocked unit tests for DEV.to adapter."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_devto_successful_publish(self):
        settings = Settings(DEVTO_API_KEY="devto-secret-api-key")
        adapter = DevtoAdapter(settings=settings)

        respx.post("https://dev.to/api/articles").respond(
            201,
            json={
                "id": 987654,
                "title": "Automated Multi-Platform Posting Launch",
                "published": True,
                "url": "https://dev.to/username/automated-multi-platform-posting-launch-abc",
                "canonical_url": "https://dev.to/username/automated-multi-platform-posting-launch-abc",
                "published_at": "2026-11-18T10:00:00Z",
            },
        )

        payload = PlatformPostPayload(
            content="Check out our new automated tool https://example.com"
        )
        result = await adapter.publish(payload)

        assert result.success is True
        assert result.platform == PlatformType.DEVTO
        assert result.external_post_id == "987654"
        assert "dev.to" in result.external_url

    @pytest.mark.asyncio
    @respx.mock
    async def test_devto_rejects_draft_status(self):
        """Part 2: Must ensure content is genuinely published; reject if saved as draft."""
        settings = Settings(DEVTO_API_KEY="devto-secret-key")
        adapter = DevtoAdapter(settings=settings)

        respx.post("https://dev.to/api/articles").respond(
            201,
            json={
                "id": 111,
                "title": "Draft Article",
                "published": False,  # API returned draft!
                "url": "https://dev.to/username/draft-article",
            },
        )

        payload = PlatformPostPayload(content="Check out https://example.com")
        with pytest.raises(PlatformContentValidationError, match="saved as a draft"):
            await adapter.publish(payload)


# ---------------------------------------------------------------------------
# 4. WordPress Adapter Unified Tests
# ---------------------------------------------------------------------------

class TestWordPressUnified:
    """Mocked unit tests for WordPress REST API adapter."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_wordpress_successful_publish(self):
        settings = Settings(
            WORDPRESS_SITE_URL="https://wp.example.com",
            WORDPRESS_USERNAME="editor",
            WORDPRESS_APP_PASSWORD="abcd efgh ijkl mnop",
        )
        adapter = WordPressAdapter(settings=settings)

        respx.post("https://wp.example.com/wp-json/wp/v2/posts").respond(
            201,
            json={
                "id": 555,
                "date_gmt": "2026-11-18T15:00:00",
                "link": "https://wp.example.com/2026/11/post-slug/",
                "status": "publish",
            },
        )

        payload = PlatformPostPayload(
            content="Exciting updates available today! https://example.com"
        )
        result = await adapter.publish(payload)

        assert result.success is True
        assert result.platform == PlatformType.WORDPRESS
        assert result.external_post_id == "555"
        assert result.external_url == "https://wp.example.com/2026/11/post-slug/"

    @pytest.mark.asyncio
    @respx.mock
    async def test_wordpress_inaccessible_site(self):
        """Part 2: Handle inaccessible WordPress sites gracefully."""
        settings = Settings(
            WORDPRESS_SITE_URL="https://inaccessible.invalid",
            WORDPRESS_USERNAME="admin",
            WORDPRESS_APP_PASSWORD="pass",
        )
        adapter = WordPressAdapter(settings=settings)

        respx.post("https://inaccessible.invalid/wp-json/wp/v2/posts").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        payload = PlatformPostPayload(content="Check out https://example.com")
        safe_res = await adapter.execute_safe_publish(payload)
        assert safe_res.success is False
        assert "PlatformNetworkError" in safe_res.error_type


# ---------------------------------------------------------------------------
# 5. Telegram Adapter Unified Tests
# ---------------------------------------------------------------------------

class TestTelegramUnified:
    """Mocked unit tests for Telegram Bot API adapter."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_telegram_public_channel_publish(self):
        settings = Settings(
            TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            TELEGRAM_CHANNEL_ID="@dxora_updates",
        )
        adapter = TelegramAdapter(settings=settings)

        respx.post(f"{adapter.bot_endpoint}/sendMessage").respond(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 789,
                    "chat": {"id": -1001234567890, "username": "dxora_updates", "type": "channel"},
                    "date": 1763480000,
                    "text": "Broadcast message https://example.com",
                },
            },
        )

        payload = PlatformPostPayload(content="Broadcast message https://example.com")
        result = await adapter.publish(payload)

        assert result.success is True
        assert result.platform == PlatformType.TELEGRAM
        assert result.external_post_id == "789"
        assert result.external_url == "https://t.me/dxora_updates/789"

    @pytest.mark.asyncio
    @respx.mock
    async def test_telegram_private_channel_suppresses_public_url(self):
        """Part 2: Private channel messages must not be falsely reported as publicly accessible."""
        settings = Settings(
            TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            TELEGRAM_CHANNEL_ID="-1009988776655",  # Private numeric chat ID without username
        )
        adapter = TelegramAdapter(settings=settings)

        respx.post(f"{adapter.bot_endpoint}/sendMessage").respond(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 404,
                    "chat": {"id": -1009988776655, "type": "channel"},  # No username
                    "date": 1763480000,
                    "text": "Private channel text https://example.com",
                },
            },
        )

        payload = PlatformPostPayload(content="Private channel text https://example.com")
        result = await adapter.publish(payload)

        assert result.success is True
        assert result.external_post_id == "404"
        assert result.external_url is None  # Accurately suppressed!


# ---------------------------------------------------------------------------
# 6. Security & Credential Masking Tests (Part 5)
# ---------------------------------------------------------------------------

class TestSecurityAndConfigurationRules:
    """Audit tests ensuring tokens and passwords are never leaked in logs or error messages."""

    def test_mask_sensitive_tokens(self):
        assert mask_sensitive_string(None) == "None"
        assert mask_sensitive_string("") == "None"
        assert mask_sensitive_string("short") == "********"
        assert mask_sensitive_string("super-secret-token-12345") == "supe...2345"

    def test_content_length_validation_rejects_oversized(self):
        """Test adapter validate_content rejects content exceeding platform limit."""
        adapter = BlueskyAdapter()
        # Bluesky limit is 300 chars
        oversized = "A" * 305 + " https://example.com"
        payload = PlatformPostPayload(content=oversized)
        val = adapter.validate_content(payload)
        assert val.is_valid is False
        assert any("exceeds bluesky limit" in err.lower() for err in val.errors)
