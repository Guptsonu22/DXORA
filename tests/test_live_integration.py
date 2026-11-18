"""Optional live integration test suite for real third-party API verification.

Strictly adheres to Master Prompt Part 9:
- Kept strictly separate from mocked unit tests.
- Never runs automatically or silently.
- Requires explicit user opt-in via ENABLE_REAL_API_TESTS="true" in environment.
- Requires real, valid credentials populated in .env.
- Skips safely by default to prevent accidental live posting during standard CI runs.
"""

import os

import pytest

from autopost_nexus.adapters.bluesky import BlueskyAdapter
from autopost_nexus.adapters.devto import DevtoAdapter
from autopost_nexus.adapters.mastodon import MastodonAdapter
from autopost_nexus.adapters.schemas import PlatformPostPayload
from autopost_nexus.adapters.telegram import TelegramAdapter
from autopost_nexus.adapters.wordpress import WordPressAdapter
from autopost_nexus.config import get_settings

# Explicit user approval flag required
ENABLE_REAL_API_TESTS = os.getenv("ENABLE_REAL_API_TESTS", "false").lower() == "true"


@pytest.mark.skipif(
    not ENABLE_REAL_API_TESTS,
    reason="Real API integration tests require explicit user approval (set ENABLE_REAL_API_TESTS=true).",
)
class TestLivePlatformIntegrations:
    """Live third-party integration tests communicating directly with remote endpoints."""

    @pytest.fixture(autouse=True)
    def setup_live_env(self):
        self.settings = get_settings()

    @pytest.mark.asyncio
    async def test_live_bluesky_publish(self):
        adapter = BlueskyAdapter(settings=self.settings)
        if not adapter.is_configured():
            pytest.skip("Bluesky live credentials not configured in environment.")

        payload = PlatformPostPayload(
            content="[Live Test] AutoPost Nexus verification. https://github.com/Guptsonu22/DXORA"
        )
        result = await adapter.publish(payload)
        assert result.success is True
        assert result.external_url is not None

    @pytest.mark.asyncio
    async def test_live_mastodon_publish(self):
        adapter = MastodonAdapter(settings=self.settings)
        if not adapter.is_configured():
            pytest.skip("Mastodon live credentials not configured in environment.")

        payload = PlatformPostPayload(
            content="[Live Test] AutoPost Nexus verification. https://github.com/Guptsonu22/DXORA"
        )
        result = await adapter.publish(payload)
        assert result.success is True
        assert result.external_url is not None

    @pytest.mark.asyncio
    async def test_live_devto_publish(self):
        adapter = DevtoAdapter(settings=self.settings)
        if not adapter.is_configured():
            pytest.skip("DEV.to live credentials not configured in environment.")

        payload = PlatformPostPayload(
            content="[Live Test] AutoPost Nexus verification. https://github.com/Guptsonu22/DXORA"
        )
        result = await adapter.publish(payload)
        assert result.success is True
        assert result.external_url is not None

    @pytest.mark.asyncio
    async def test_live_wordpress_publish(self):
        adapter = WordPressAdapter(settings=self.settings)
        if not adapter.is_configured():
            pytest.skip("WordPress live credentials not configured in environment.")

        payload = PlatformPostPayload(
            content="[Live Test] AutoPost Nexus verification. https://github.com/Guptsonu22/DXORA"
        )
        result = await adapter.publish(payload)
        assert result.success is True
        assert result.external_url is not None

    @pytest.mark.asyncio
    async def test_live_telegram_publish(self):
        adapter = TelegramAdapter(settings=self.settings)
        if not adapter.is_configured():
            pytest.skip("Telegram live credentials not configured in environment.")

        payload = PlatformPostPayload(
            content="[Live Test] AutoPost Nexus verification. https://github.com/Guptsonu22/DXORA"
        )
        result = await adapter.publish(payload)
        assert result.success is True
