"""Comprehensive test suite for Phase 8: Official Telegram Bot API Adapter.

Validates:
- Bot API token authentication
- Configurable target channel ID (public @channel vs private -100xxxxxxxxxx)
- Message publishing via POST /sendMessage
- Extraction of returned message ID
- Public channel message URL generation (https://t.me/{username}/{message_id})
- Private channel message URL suppression (external_url is None to avoid invalid URLs)
- Permission enforcement: traps 403 (lack of posting rights, not admin, kicked)
- Invalid token errors (401) and chat errors (400)
- Native Telegram rate limit parsing (parameters.retry_after)
- Health diagnostics via /getMe and /getChat
"""

import httpx
import pytest
import respx

from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformNetworkError,
    PlatformRateLimitError,
    PlatformServerError,
)
from autopost_nexus.adapters.schemas import (
    PlatformPostPayload,
    PublishFailure,
    PublishResult,
)
from autopost_nexus.adapters.telegram import TelegramAdapter
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


@pytest.fixture
def telegram_public_settings() -> Settings:
    """Settings configured with public channel @dxoratech."""
    return Settings(
        TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456",
        TELEGRAM_CHANNEL_ID="@dxoratech",
        TELEGRAM_API_BASE="https://api.telegram.org",
    )


@pytest.fixture
def telegram_private_settings() -> Settings:
    """Settings configured with private channel ID -1001987654321."""
    return Settings(
        TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456",
        TELEGRAM_CHANNEL_ID="-1001987654321",
        TELEGRAM_API_BASE="https://api.telegram.org",
    )


@pytest.fixture
def public_adapter(telegram_public_settings: Settings) -> TelegramAdapter:
    """Provide TelegramAdapter configured for a public channel."""
    return TelegramAdapter(settings=telegram_public_settings)


@pytest.fixture
def private_adapter(telegram_private_settings: Settings) -> TelegramAdapter:
    """Provide TelegramAdapter configured for a private channel."""
    return TelegramAdapter(settings=telegram_private_settings)


# ---------------------------------------------------------------------------
# 1. Properties & Configuration Tests
# ---------------------------------------------------------------------------


def test_telegram_adapter_properties(public_adapter: TelegramAdapter):
    """Verify standard properties conforming to BasePlatformAdapter."""
    assert public_adapter.platform_type == PlatformType.TELEGRAM
    assert public_adapter.max_characters == 4096
    assert "Bot Token" in public_adapter.auth_mode
    assert public_adapter.is_configured() is True
    assert public_adapter.channel_id == "@dxoratech"
    assert "123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456" in public_adapter.bot_endpoint


def test_telegram_unconfigured_detection():
    """Verify is_configured returns False when token or channel ID is absent."""
    empty1 = Settings(TELEGRAM_BOT_TOKEN=None, TELEGRAM_CHANNEL_ID="@test")
    assert TelegramAdapter(settings=empty1).is_configured() is False

    empty2 = Settings(TELEGRAM_BOT_TOKEN="token123", TELEGRAM_CHANNEL_ID=None)
    assert TelegramAdapter(settings=empty2).is_configured() is False


# ---------------------------------------------------------------------------
# 2. Public vs Private Channel Message URL Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_to_public_channel_generates_public_url(public_adapter: TelegramAdapter):
    """Verify public channel post returns valid public URL: https://t.me/{username}/{message_id}."""
    mock_response = {
        "ok": True,
        "result": {
            "message_id": 99123,
            "chat": {
                "id": -1001234567890,
                "title": "Dxora Tech Public Updates",
                "type": "channel",
                "username": "dxoratech",
            },
            "date": 1731860000,
            "text": "Check out our latest release! https://dxora.tech",
        },
    }

    route = respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(status_code=200, json=mock_response)

    payload = PlatformPostPayload(
        content="Check out our latest release! https://dxora.tech",
    )

    result = await public_adapter.publish(payload)

    # 1. Verify PublishResult
    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.platform == PlatformType.TELEGRAM
    assert result.external_post_id == "99123"
    # Public URL generated because channel has username
    assert result.external_url == "https://t.me/dxoratech/99123"
    assert result.latency_ms > 0

    # 2. Verify wire payload
    assert route.called
    sent_json = route.calls.last.request.read().decode("utf-8")
    assert '"chat_id":"@dxoratech"' in sent_json or '"chat_id": "@dxoratech"' in sent_json
    assert "Check out our latest release!" in sent_json


@pytest.mark.asyncio
@respx.mock
async def test_publish_to_private_channel_suppresses_public_url(private_adapter: TelegramAdapter):
    """Verify critical requirement: Private channel messages must NOT generate an invalid public URL."""
    mock_private_response = {
        "ok": True,
        "result": {
            "message_id": 88456,
            "chat": {
                "id": -1001987654321,
                "title": "Confidential Internal Channel",
                "type": "channel",
                "username": None,  # Private channel: no username!
            },
            "date": 1731860000,
            "text": "Internal announcement. https://internal.dxora.tech",
        },
    }

    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(status_code=200, json=mock_private_response)

    payload = PlatformPostPayload(
        content="Internal announcement. https://internal.dxora.tech",
    )

    result = await private_adapter.publish(payload)

    assert result.success is True
    assert result.external_post_id == "88456"
    # MUST BE None: Private channel cannot produce a working public URL
    assert result.external_url is None


# ---------------------------------------------------------------------------
# 3. Permission Enforcement & Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_permission_error_403(public_adapter: TelegramAdapter):
    """Verify critical requirement: Require bot posting permission.

    HTTP 403 (lack of posting rights or bot not admin) raises PlatformAuthenticationError.
    """
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=403,
        json={
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: not enough rights to post text messages to the chat",
        },
    )

    payload = PlatformPostPayload(content="Permission test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 403
    assert "not enough rights to post text messages" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_bot_kicked_error_403(public_adapter: TelegramAdapter):
    """Verify bot kicked from channel raises PlatformAuthenticationError."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=403,
        json={
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: bot was kicked from the channel chat",
        },
    )

    payload = PlatformPostPayload(content="Kicked test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 403
    assert "bot was kicked" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_auth_error_401_invalid_token(public_adapter: TelegramAdapter):
    """Verify invalid bot token raises PlatformAuthenticationError with retryable=False."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=401,
        json={"ok": False, "error_code": 401, "description": "Unauthorized"},
    )

    payload = PlatformPostPayload(content="Invalid token test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 401
    assert "Unauthorized" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_bad_request_400_chat_not_found(public_adapter: TelegramAdapter):
    """Verify non-existent channel returns HTTP 400 and raises PlatformContentValidationError."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=400,
        json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
    )

    payload = PlatformPostPayload(content="Chat not found test")
    with pytest.raises(PlatformContentValidationError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
    assert "chat not found" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_rate_limit_error_429_with_parameters_retry_after(
    public_adapter: TelegramAdapter,
):
    """Verify Telegram parameters.retry_after is correctly parsed on HTTP 429."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=429,
        json={
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after 25",
            "parameters": {"retry_after": 25},
        },
    )

    payload = PlatformPostPayload(content="Rate limit test")
    with pytest.raises(PlatformRateLimitError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 25.0


@pytest.mark.asyncio
@respx.mock
async def test_publish_server_error_502(public_adapter: TelegramAdapter):
    """Verify Telegram 502 Bad Gateway raises PlatformServerError with retryable=True."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=502,
        text="Bad Gateway",
    )

    payload = PlatformPostPayload(content="Server outage test")
    with pytest.raises(PlatformServerError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
@respx.mock
async def test_publish_network_timeout(public_adapter: TelegramAdapter):
    """Verify connection timeout raises PlatformNetworkError with retryable=True."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).mock(side_effect=httpx.ConnectTimeout("Connection to api.telegram.org timed out"))

    payload = PlatformPostPayload(content="Timeout test")
    with pytest.raises(PlatformNetworkError) as exc_info:
        await public_adapter.publish(payload)

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_execute_safe_publish_converts_error_to_failure(public_adapter: TelegramAdapter):
    """Verify execute_safe_publish traps errors and returns PublishFailure."""
    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/sendMessage"
    ).respond(
        status_code=401,
        json={"ok": False, "description": "Unauthorized"},
    )

    payload = PlatformPostPayload(content="Safe publish test")
    failure = await public_adapter.execute_safe_publish(payload)

    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.platform == PlatformType.TELEGRAM
    assert failure.error_type == "PlatformAuthenticationError"
    assert failure.retryable is False
    assert failure.status_code == 401


# ---------------------------------------------------------------------------
# 4. Health Diagnostics Tests (/getMe & /getChat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_telegram_health_check_healthy(public_adapter: TelegramAdapter):
    """Verify health check returns PlatformHealthResult with is_healthy=True."""
    respx.get(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/getMe"
    ).respond(
        status_code=200,
        json={"ok": True, "result": {"id": 123456789, "username": "dxora_posting_bot", "first_name": "DxoraBot"}},
    )

    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/getChat"
    ).respond(
        status_code=200,
        json={
            "ok": True,
            "result": {
                "id": -1001234567890,
                "title": "Dxora Official Announcements",
                "type": "channel",
                "username": "dxoratech",
            },
        },
    )

    health = await public_adapter.check_health()
    assert health.is_healthy is True
    assert health.is_configured is True
    assert "@dxora_posting_bot" in health.details
    assert "Dxora Official Announcements" in health.details
    assert health.latency_ms is not None


@pytest.mark.asyncio
@respx.mock
async def test_telegram_health_check_invalid_bot_token(public_adapter: TelegramAdapter):
    """Verify health check detects invalid bot token (HTTP 401 on /getMe)."""
    respx.get(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/getMe"
    ).respond(
        status_code=401,
        json={"ok": False, "error_code": 401, "description": "Unauthorized"},
    )

    health = await public_adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is True
    assert "401" in health.details


@pytest.mark.asyncio
@respx.mock
async def test_telegram_health_check_lacks_channel_permissions_403(public_adapter: TelegramAdapter):
    """Verify health check detects lack of channel permissions (HTTP 403 on /getChat)."""
    respx.get(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/getMe"
    ).respond(
        status_code=200,
        json={"ok": True, "result": {"id": 123456789, "username": "dxora_posting_bot"}},
    )

    respx.post(
        "https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456/getChat"
    ).respond(
        status_code=403,
        json={"ok": False, "error_code": 403, "description": "Forbidden: bot is not a member of the channel chat"},
    )

    health = await public_adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is True
    assert "lacks administrator or posting permissions" in health.details


@pytest.mark.asyncio
async def test_telegram_health_check_unconfigured():
    """Verify health check returns unconfigured status when credentials are missing."""
    empty_settings = Settings(TELEGRAM_BOT_TOKEN=None, TELEGRAM_CHANNEL_ID=None)
    adapter = TelegramAdapter(settings=empty_settings)

    health = await adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is False
    assert "not configured" in health.details
