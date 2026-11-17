"""Comprehensive test suite for Phase 5: Official Mastodon (Fediverse) Adapter.

Validates OAuth 2.0 Bearer token authentication, status publishing,
public visibility, idempotency keys, permalink extraction, rate limiting,
error handling, X-RateLimit-Reset ISO 8601 parsing, and account verification
health checks — all aligned with docs.joinmastodon.org/methods/statuses/.
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
from autopost_nexus.adapters.mastodon import MastodonAdapter
from autopost_nexus.adapters.schemas import (
    PlatformPostPayload,
    PublishFailure,
    PublishResult,
)
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


@pytest.fixture
def mastodon_settings() -> Settings:
    """Provide Settings configured with test Mastodon credentials."""
    return Settings(
        MASTODON_ACCESS_TOKEN="mstdn_test_access_token_12345",
        MASTODON_INSTANCE_URL="https://mastodon.social",
    )


@pytest.fixture
def mastodon_adapter(mastodon_settings: Settings) -> MastodonAdapter:
    """Provide configured MastodonAdapter instance."""
    return MastodonAdapter(settings=mastodon_settings)


# ---------------------------------------------------------------------------
# 1. Properties & Configuration Tests
# ---------------------------------------------------------------------------


def test_mastodon_adapter_properties(mastodon_adapter: MastodonAdapter):
    """Verify standard properties conforming to BasePlatformAdapter."""
    assert mastodon_adapter.platform_type == PlatformType.MASTODON
    assert mastodon_adapter.max_characters == 500
    assert "OAuth 2.0 Bearer" in mastodon_adapter.auth_mode
    assert mastodon_adapter.is_configured() is True
    assert mastodon_adapter.instance_url == "https://mastodon.social"


def test_mastodon_instance_url_trailing_slash_normalization():
    """Verify that trailing slashes are stripped from instance URLs."""
    settings = Settings(
        MASTODON_ACCESS_TOKEN="test_token",
        MASTODON_INSTANCE_URL="https://fosstodon.org/",
    )
    adapter = MastodonAdapter(settings=settings)
    assert adapter.instance_url == "https://fosstodon.org"


def test_mastodon_unconfigured_detection():
    """Verify is_configured returns False when access token is absent."""
    empty_settings = Settings(MASTODON_ACCESS_TOKEN=None)
    adapter = MastodonAdapter(settings=empty_settings)
    assert adapter.is_configured() is False


# ---------------------------------------------------------------------------
# 2. Status Publishing & Permalink Extraction Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_public_status_success_with_permalink(mastodon_adapter: MastodonAdapter):
    """Verify publishing a public status and extracting the public permalink."""
    mock_status_response = {
        "id": "111953284920194821",
        "created_at": "2026-11-17T16:40:00.000Z",
        "url": "https://mastodon.social/@dxoratech/111953284920194821",
        "uri": "https://mastodon.social/users/dxoratech/statuses/111953284920194821",
        "content": "<p>Hello from AutoPost Nexus on Mastodon! 🐘</p>",
        "visibility": "public",
    }

    route = respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=200,
        json=mock_status_response,
    )

    payload = PlatformPostPayload(
        content="Hello from AutoPost Nexus on Mastodon! 🐘",
    )

    result = await mastodon_adapter.publish(payload)

    # Verify PublishResult
    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.platform == PlatformType.MASTODON
    assert result.external_post_id == "111953284920194821"
    assert result.external_url == "https://mastodon.social/@dxoratech/111953284920194821"
    assert result.latency_ms > 0

    # Verify outbound request headers and payload
    assert route.called
    sent_request = route.calls.last.request
    assert sent_request.headers.get("Authorization") == "Bearer mstdn_test_access_token_12345"
    assert "Idempotency-Key" in sent_request.headers

    sent_body = sent_request.read().decode("utf-8")
    assert "Hello from AutoPost Nexus" in sent_body
    assert '"visibility":"public"' in sent_body or '"visibility": "public"' in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_publish_status_with_spoiler_and_custom_idempotency_key(
    mastodon_adapter: MastodonAdapter,
):
    """Verify that title is mapped to spoiler_text (content warning) and idempotency key is forwarded."""
    route = respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=200,
        json={
            "id": "1119539999",
            "url": "https://mastodon.social/@dxoratech/1119539999",
            "visibility": "public",
        },
    )

    payload = PlatformPostPayload(
        title="Spoiler Alert / Major Feature",
        content="Here are the secret release details...",
        metadata={"idempotency_key": "custom-mstdn-idemp-001"},
    )

    result = await mastodon_adapter.publish(payload)
    assert result.success is True

    sent_request = route.calls.last.request
    assert sent_request.headers.get("Idempotency-Key") == "custom-mstdn-idemp-001"
    sent_body = sent_request.read().decode("utf-8")
    assert "Spoiler Alert / Major Feature" in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_publish_uses_uri_fallback_when_url_absent(mastodon_adapter: MastodonAdapter):
    """Verify permalink falls back to 'uri' field when 'url' is not present in response.

    Per Mastodon API spec: 'url' is the public link, 'uri' is the ActivityPub URI.
    Some Mastodon forks / Pleroma instances may omit 'url'.
    """
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=200,
        json={
            "id": "222953284920194822",
            "uri": "https://mastodon.social/users/dxoratech/statuses/222953284920194822",
            # 'url' intentionally absent to test fallback
        },
    )

    payload = PlatformPostPayload(content="Testing URI fallback for permalink extraction.")
    result = await mastodon_adapter.publish(payload)

    assert result.success is True
    assert result.external_post_id == "222953284920194822"
    # Should use uri as fallback
    assert "222953284920194822" in result.external_url


# ---------------------------------------------------------------------------
# 3. Error Handling Tests (401, 403, 422, 429, 503, Network Timeout)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_auth_error_401(mastodon_adapter: MastodonAdapter):
    """Verify HTTP 401 raises PlatformAuthenticationError with retryable=False."""
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=401,
        json={"error": "The access token is invalid"},
    )

    payload = PlatformPostPayload(content="Auth failure test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 401
    assert "The access token is invalid" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_auth_error_403(mastodon_adapter: MastodonAdapter):
    """Verify HTTP 403 Forbidden raises PlatformAuthenticationError (insufficient scope)."""
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=403,
        json={"error": "This action is not allowed"},
    )

    payload = PlatformPostPayload(content="Forbidden action test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_publish_validation_error_422(mastodon_adapter: MastodonAdapter):
    """Verify HTTP 422 raises PlatformContentValidationError with retryable=False."""
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=422,
        json={"error": "Validation failed: Text is too long (maximum is 500 characters)"},
    )

    payload = PlatformPostPayload(content="Too long content")
    with pytest.raises(PlatformContentValidationError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 422
    assert "Text is too long" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_rate_limit_error_429_with_retry_after(mastodon_adapter: MastodonAdapter):
    """Verify HTTP 429 raises PlatformRateLimitError with Retry-After parsed."""
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=429,
        headers={"Retry-After": "30"},
        json={"error": "Rate limit exceeded"},
    )

    payload = PlatformPostPayload(content="High frequency status")
    with pytest.raises(PlatformRateLimitError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 30.0


@pytest.mark.asyncio
@respx.mock
async def test_publish_rate_limit_x_ratelimit_reset_iso8601(mastodon_adapter: MastodonAdapter):
    """Verify X-RateLimit-Reset ISO 8601 datetime is correctly parsed for cooldown.

    Per official Mastodon API docs: X-RateLimit-Reset is an ISO 8601 datetime string
    (e.g. '2026-11-17T17:00:00.000Z'), not a Unix timestamp.
    """
    # Set reset time to 60 seconds in the future
    from datetime import UTC, datetime, timedelta

    future_reset = (datetime.now(UTC) + timedelta(seconds=60)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=429,
        headers={"X-RateLimit-Reset": future_reset},
        json={"error": "Rate limit exceeded"},
    )

    payload = PlatformPostPayload(content="Rate limit ISO 8601 test")
    with pytest.raises(PlatformRateLimitError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is True
    # Cooldown should be approximately 60 seconds (allow ±5s tolerance)
    assert exc_info.value.retry_after_seconds is not None
    assert 55.0 <= exc_info.value.retry_after_seconds <= 65.0


@pytest.mark.asyncio
@respx.mock
async def test_publish_server_error_503(mastodon_adapter: MastodonAdapter):
    """Verify HTTP 503 raises PlatformServerError with retryable=True."""
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=503,
        text="Mastodon instance undergoing database maintenance",
    )

    payload = PlatformPostPayload(content="Maintenance test")
    with pytest.raises(PlatformServerError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
@respx.mock
async def test_publish_network_timeout(mastodon_adapter: MastodonAdapter):
    """Verify socket timeout raises PlatformNetworkError with retryable=True."""
    respx.post("https://mastodon.social/api/v1/statuses").mock(
        side_effect=httpx.ConnectTimeout("Connection timed out to mastodon.social")
    )

    payload = PlatformPostPayload(content="Timeout test")
    with pytest.raises(PlatformNetworkError) as exc_info:
        await mastodon_adapter.publish(payload)

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_execute_safe_publish_converts_error_to_failure(mastodon_adapter: MastodonAdapter):
    """Verify execute_safe_publish catches exceptions and returns PublishFailure."""
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        status_code=401,
        json={"error": "The access token was revoked"},
    )

    payload = PlatformPostPayload(content="Safe publish test")
    failure = await mastodon_adapter.execute_safe_publish(payload)

    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.platform == PlatformType.MASTODON
    assert failure.error_type == "PlatformAuthenticationError"
    assert failure.retryable is False
    assert failure.status_code == 401


# ---------------------------------------------------------------------------
# 4. Content Validation & Health Check Tests
# ---------------------------------------------------------------------------


def test_mastodon_content_length_validation(mastodon_adapter: MastodonAdapter):
    """Verify character limit (500 characters per official Mastodon default)."""
    valid_payload = PlatformPostPayload(content="M" * 500)
    assert mastodon_adapter.validate_content(valid_payload).is_valid is True

    overflow_payload = PlatformPostPayload(content="M" * 501)
    val = mastodon_adapter.validate_content(overflow_payload)
    assert val.is_valid is False
    assert "exceeds mastodon limit of 500 characters" in val.errors[0].lower()


@pytest.mark.asyncio
@respx.mock
async def test_mastodon_health_check_healthy(mastodon_adapter: MastodonAdapter):
    """Verify health check returns PlatformHealthResult via verify_credentials."""
    respx.get("https://mastodon.social/api/v1/accounts/verify_credentials").respond(
        status_code=200,
        json={
            "id": "10987654321",
            "username": "dxoratech",
            "acct": "dxoratech@mastodon.social",
            "display_name": "Dxora Technologies",
        },
    )

    health = await mastodon_adapter.check_health()
    assert health.is_healthy is True
    assert health.is_configured is True
    assert "@dxoratech@mastodon.social" in health.details
    assert health.latency_ms is not None


@pytest.mark.asyncio
async def test_mastodon_health_check_unconfigured():
    """Verify health check returns unconfigured status when token is missing."""
    empty_settings = Settings(MASTODON_ACCESS_TOKEN=None)
    adapter = MastodonAdapter(settings=empty_settings)

    health = await adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is False
    assert "not configured" in health.details


@pytest.mark.asyncio
@respx.mock
async def test_mastodon_health_check_auth_failure(mastodon_adapter: MastodonAdapter):
    """Verify health check detects invalid token (HTTP 401 on verify_credentials)."""
    respx.get("https://mastodon.social/api/v1/accounts/verify_credentials").respond(
        status_code=401,
        json={"error": "The access token is invalid"},
    )

    health = await mastodon_adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is True
    assert "401" in health.details
