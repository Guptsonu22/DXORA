"""Comprehensive test suite for Phase 4: Official Bluesky (AT Protocol) Adapter.

Validates authentication (createSession), post creation (createRecord),
rich text URL facet extraction (UTF-8 byte offsets), web URL generation,
token refresh, rate-limit handling, and error mapping.
"""

import httpx
import pytest
import respx

from autopost_nexus.adapters.bluesky import BlueskyAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformRateLimitError,
    PlatformServerError,
)
from autopost_nexus.adapters.schemas import (
    PlatformPostPayload,
    PublishFailure,
    PublishResult,
)
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


@pytest.fixture
def bsky_settings() -> Settings:
    """Provide Settings configured with test Bluesky credentials."""
    return Settings(
        BLUESKY_HANDLE="dxora.bsky.social",
        BLUESKY_APP_PASSWORD="test-app-password-xyz",
        BLUESKY_SERVICE_URL="https://bsky.social",
    )


@pytest.fixture
def bsky_adapter(bsky_settings: Settings) -> BlueskyAdapter:
    """Provide configured BlueskyAdapter instance."""
    return BlueskyAdapter(settings=bsky_settings)


# ---------------------------------------------------------------------------
# 1. Properties & Configuration Tests
# ---------------------------------------------------------------------------


def test_bluesky_adapter_properties(bsky_adapter: BlueskyAdapter):
    """Verify standard properties conforming to BasePlatformAdapter."""
    assert bsky_adapter.platform_type == PlatformType.BLUESKY
    assert bsky_adapter.max_characters == 300
    assert "AT Protocol" in bsky_adapter.auth_mode
    assert bsky_adapter.is_configured() is True


def test_bluesky_unconfigured_detection():
    """Verify is_configured returns False when credentials are missing."""
    empty_settings = Settings(BLUESKY_HANDLE=None, BLUESKY_APP_PASSWORD=None)
    adapter = BlueskyAdapter(settings=empty_settings)
    assert adapter.is_configured() is False


# ---------------------------------------------------------------------------
# 2. Rich Text URL & Hashtag Facet Extraction Tests (UTF-8 Byte Accuracy)
# ---------------------------------------------------------------------------


def test_extract_facets_single_url():
    """Verify single URL extraction with exact byte offsets."""
    text = "Visit our website at https://dxora.tech today!"
    facets = BlueskyAdapter.extract_facets(text)

    assert len(facets) == 1
    facet = facets[0]
    assert facet["$type"] == "app.bsky.richtext.facet"
    assert facet["features"][0]["$type"] == "app.bsky.richtext.facet#link"
    assert facet["features"][0]["uri"] == "https://dxora.tech"

    # Verify byte offsets on raw UTF-8 bytes
    b_text = text.encode("utf-8")
    start = facet["index"]["byteStart"]
    end = facet["index"]["byteEnd"]
    assert b_text[start:end].decode("utf-8") == "https://dxora.tech"


def test_extract_facets_multi_byte_emoji_handling():
    """Verify UTF-8 byte offsets when text contains multi-byte characters (emojis)."""
    # 🚀 is 4 bytes in UTF-8
    text = "🚀 Launch! Read more at https://dxora.tech/launch #dxora"
    facets = BlueskyAdapter.extract_facets(text)

    assert len(facets) == 2  # 1 link, 1 hashtag

    link_facet = next(
        f for f in facets if f["features"][0]["$type"] == "app.bsky.richtext.facet#link"
    )
    tag_facet = next(
        f for f in facets if f["features"][0]["$type"] == "app.bsky.richtext.facet#tag"
    )

    b_text = text.encode("utf-8")

    # Link slice check
    l_start = link_facet["index"]["byteStart"]
    l_end = link_facet["index"]["byteEnd"]
    assert b_text[l_start:l_end].decode("utf-8") == "https://dxora.tech/launch"

    # Hashtag slice check
    t_start = tag_facet["index"]["byteStart"]
    t_end = tag_facet["index"]["byteEnd"]
    assert b_text[t_start:t_end].decode("utf-8") == "#dxora"
    assert tag_facet["features"][0]["tag"] == "dxora"


def test_extract_facets_strips_trailing_punctuation():
    """Verify trailing commas and periods are stripped from extracted URLs."""
    text = "Check out https://dxora.tech, and https://github.com/dxora."
    facets = BlueskyAdapter.extract_facets(text)

    assert len(facets) == 2
    assert facets[0]["features"][0]["uri"] == "https://dxora.tech"
    assert facets[1]["features"][0]["uri"] == "https://github.com/dxora"


# ---------------------------------------------------------------------------
# 3. Authentication (createSession) Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_session_success(bsky_adapter: BlueskyAdapter):
    """Verify successful AT Protocol session creation and caching."""
    session_response = {
        "accessJwt": "jwt.access.token.12345",
        "refreshJwt": "jwt.refresh.token.67890",
        "did": "did:plc:dxora12345678",
        "handle": "dxora.bsky.social",
        "email": "dev@dxora.tech",
    }

    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json=session_response,
    )

    session = await bsky_adapter.create_session()
    assert session["accessJwt"] == "jwt.access.token.12345"
    assert session["did"] == "did:plc:dxora12345678"
    assert session["handle"] == "dxora.bsky.social"


@pytest.mark.asyncio
@respx.mock
async def test_create_session_auth_failure(bsky_adapter: BlueskyAdapter):
    """Verify HTTP 401 raises PlatformAuthenticationError with non-retryable flag."""
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=401,
        json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"},
    )

    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await bsky_adapter.create_session()

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 401
    assert "Invalid identifier or password" in exc_info.value.message


# ---------------------------------------------------------------------------
# 4. Post Creation (createRecord) & URL Extraction Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_post_with_facets_and_public_url(bsky_adapter: BlueskyAdapter):
    """Verify complete publishing flow: session creation -> record creation -> web URL construction."""
    # 1. Mock session creation
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json={
            "accessJwt": "jwt.access.token",
            "did": "did:plc:dxora_publisher",
            "handle": "dxora.bsky.social",
        },
    )

    # 2. Mock record creation
    record_route = respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").respond(
        status_code=200,
        json={
            "uri": "at://did:plc:dxora_publisher/app.bsky.feed.post/3lcf998877",
            "cid": "bafyreihdxoracid123456",
        },
    )

    payload = PlatformPostPayload(
        content="Automated multi-platform posting live on Bluesky! Visit https://dxora.tech #python"
    )

    result = await bsky_adapter.publish(payload)

    # Verify PublishResult
    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.platform == PlatformType.BLUESKY
    assert result.external_post_id == "at://did:plc:dxora_publisher/app.bsky.feed.post/3lcf998877"
    assert result.external_url == "https://bsky.app/profile/dxora.bsky.social/post/3lcf998877"
    assert result.latency_ms > 0

    # Verify wire payload passed to AT Protocol
    assert record_route.called
    sent_json = record_route.calls.last.request.read().decode("utf-8")
    assert "app.bsky.feed.post" in sent_json
    assert "did:plc:dxora_publisher" in sent_json
    assert "https://dxora.tech" in sent_json
    assert "dxora" in sent_json


@pytest.mark.asyncio
@respx.mock
async def test_publish_token_refresh_on_401(bsky_adapter: BlueskyAdapter):
    """Verify that an expired access token automatically triggers session refresh and retry."""
    # Pre-seed cached session with stale token
    bsky_adapter._cached_session = {
        "accessJwt": "stale_token_abc",
        "did": "did:plc:dxora_publisher",
        "handle": "dxora.bsky.social",
    }

    # First createRecord call returns 401 ExpiredToken
    # Second createRecord call returns 200 OK
    respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").side_effect = [
        httpx.Response(401, json={"error": "ExpiredToken", "message": "Token has expired"}),
        httpx.Response(
            200,
            json={
                "uri": "at://did:plc:dxora_publisher/app.bsky.feed.post/3lcf112233",
                "cid": "bafytest",
            },
        ),
    ]

    # Refresh session endpoint
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json={
            "accessJwt": "fresh_refreshed_token",
            "did": "did:plc:dxora_publisher",
            "handle": "dxora.bsky.social",
        },
    )

    payload = PlatformPostPayload(content="Testing automatic token refresh on expired session.")
    result = await bsky_adapter.publish(payload)

    assert result.success is True
    assert "3lcf112233" in result.external_post_id
    assert bsky_adapter._cached_session["accessJwt"] == "fresh_refreshed_token"


# ---------------------------------------------------------------------------
# 5. Error Handling Tests (Rate Limit, Server Error, Validation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_rate_limit_error(bsky_adapter: BlueskyAdapter):
    """Verify HTTP 429 raises PlatformRateLimitError with retryable=True and Retry-After cooldown."""
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json={"accessJwt": "valid_token", "did": "did:plc:dxora", "handle": "dxora.bsky.social"},
    )
    respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").respond(
        status_code=429,
        headers={"Retry-After": "45"},
        json={"error": "RateLimitExceeded", "message": "Rate limit exceeded for endpoint"},
    )

    payload = PlatformPostPayload(content="Message during peak traffic")
    with pytest.raises(PlatformRateLimitError) as exc_info:
        await bsky_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 45.0


@pytest.mark.asyncio
@respx.mock
async def test_publish_content_validation_rejection(bsky_adapter: BlueskyAdapter):
    """Verify HTTP 400 raises PlatformContentValidationError with non-retryable flag."""
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json={"accessJwt": "valid_token", "did": "did:plc:dxora", "handle": "dxora.bsky.social"},
    )
    respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").respond(
        status_code=400,
        json={"error": "InvalidRequest", "message": "Record text cannot be empty"},
    )

    payload = PlatformPostPayload(content="Some invalid post")
    with pytest.raises(PlatformContentValidationError) as exc_info:
        await bsky_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
    assert "Record text cannot be empty" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_server_error_503(bsky_adapter: BlueskyAdapter):
    """Verify HTTP 503 raises PlatformServerError with retryable=True."""
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json={"accessJwt": "valid_token", "did": "did:plc:dxora", "handle": "dxora.bsky.social"},
    )
    respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").respond(
        status_code=503,
        text="Service Unavailable",
    )

    payload = PlatformPostPayload(content="Server outage test")
    with pytest.raises(PlatformServerError) as exc_info:
        await bsky_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
@respx.mock
async def test_execute_safe_publish_converts_error_to_failure(bsky_adapter: BlueskyAdapter):
    """Verify execute_safe_publish catches exceptions and returns PublishFailure."""
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=401,
        json={"error": "AuthenticationRequired", "message": "Bad credentials"},
    )

    payload = PlatformPostPayload(content="Safe publish test")
    failure = await bsky_adapter.execute_safe_publish(payload)

    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.platform == PlatformType.BLUESKY
    assert failure.error_type == "PlatformAuthenticationError"
    assert failure.retryable is False
    assert failure.status_code == 401


# ---------------------------------------------------------------------------
# 6. Content Validation & Health Check Tests
# ---------------------------------------------------------------------------


def test_bluesky_content_length_validation(bsky_adapter: BlueskyAdapter):
    """Verify character limit (300 graphemes/characters)."""
    valid_payload = PlatformPostPayload(content="A" * 300)
    assert bsky_adapter.validate_content(valid_payload).is_valid is True

    overflow_payload = PlatformPostPayload(content="A" * 301)
    val = bsky_adapter.validate_content(overflow_payload)
    assert val.is_valid is False
    assert "exceeds bluesky limit of 300 characters" in val.errors[0].lower()


@pytest.mark.asyncio
@respx.mock
async def test_bluesky_health_check_healthy(bsky_adapter: BlueskyAdapter):
    """Verify health check returns PlatformHealthResult with is_healthy=True."""
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        status_code=200,
        json={
            "accessJwt": "jwt.access",
            "did": "did:plc:dxora_healthy",
            "handle": "dxora.bsky.social",
        },
    )

    health = await bsky_adapter.check_health()
    assert health.is_healthy is True
    assert health.is_configured is True
    assert "@dxora.bsky.social" in health.details
    assert health.latency_ms is not None
