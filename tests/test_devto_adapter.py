"""Comprehensive test suite for Phase 6: Official DEV.to (Forem API v1) Adapter.

Validates:
- API key authentication via `api-key` header
- Article publishing via POST /api/articles
- Conversion of short messages into article title and body
- Enforcement of `published=true`
- Strict verification that drafts (published=false) are rejected
- Canonical URL extraction
- Rate limiting (429 + Retry-After)
- Authentication errors (401/403) and validation errors (422)
- Server errors (500/503) and network timeouts
- Health checks via GET /api/users/me
"""

import httpx
import pytest
import respx

from autopost_nexus.adapters.devto import DevtoAdapter
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
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


@pytest.fixture
def devto_settings() -> Settings:
    """Provide Settings configured with test DEV.to credentials."""
    return Settings(
        DEVTO_API_KEY="devto_test_secret_api_key_12345",
        DEVTO_BASE_URL="https://dev.to",
    )


@pytest.fixture
def devto_adapter(devto_settings: Settings) -> DevtoAdapter:
    """Provide configured DevtoAdapter instance."""
    return DevtoAdapter(settings=devto_settings)


# ---------------------------------------------------------------------------
# 1. Properties & Configuration Tests
# ---------------------------------------------------------------------------


def test_devto_adapter_properties(devto_adapter: DevtoAdapter):
    """Verify standard properties conforming to BasePlatformAdapter."""
    assert devto_adapter.platform_type == PlatformType.DEVTO
    assert devto_adapter.max_characters == 65536
    assert "api-key" in devto_adapter.auth_mode
    assert devto_adapter.is_configured() is True
    assert devto_adapter.base_url == "https://dev.to"


def test_devto_base_url_trailing_slash_normalization():
    """Verify that trailing slashes are cleanly stripped from base URL."""
    settings = Settings(
        DEVTO_API_KEY="test_key",
        DEVTO_BASE_URL="https://forem.example.org/",
    )
    adapter = DevtoAdapter(settings=settings)
    assert adapter.base_url == "https://forem.example.org"


def test_devto_unconfigured_detection():
    """Verify is_configured returns False when API key is missing."""
    empty_settings = Settings(DEVTO_API_KEY=None)
    adapter = DevtoAdapter(settings=empty_settings)
    assert adapter.is_configured() is False


# ---------------------------------------------------------------------------
# 2. Content Formatting: Title, Body, Canonical URL & Tags Generation
# ---------------------------------------------------------------------------


def test_format_article_explicit_title(devto_adapter: DevtoAdapter):
    """Verify explicit title is preserved and CTA URL becomes canonical URL."""
    payload = PlatformPostPayload(
        title="Breaking Tech News for Developers",
        content="Our new automation framework is live at https://dxora.tech/nexus #python #webdev",
    )
    title, body, canonical_url, _tags = devto_adapter.format_article(payload)

    assert title == "Breaking Tech News for Developers"
    assert "Our new automation framework is live" in body
    assert canonical_url == "https://dxora.tech/nexus"
    assert "python" in tags
    assert "webdev" in tags


def test_format_article_generates_meaningful_title_from_short_message(devto_adapter: DevtoAdapter):
    """Verify that a short message without title generates an appropriate article headline."""
    payload = PlatformPostPayload(
        content="Check out our latest business platform and grow your online visibility. https://example.com",
    )
    title, body, canonical_url, _tags = devto_adapter.format_article(payload)

    # First clause before period/URL should form the title
    assert "Check out our latest business platform" in title
    assert "https://" not in title
    assert canonical_url == "https://example.com"
    assert "https://example.com" in body


def test_format_article_fallback_title_for_url_only_message(devto_adapter: DevtoAdapter):
    """Verify clean fallback title when message only contains a URL."""
    payload = PlatformPostPayload(content="https://dxora.tech")
    title, _body, canonical_url, _ = devto_adapter.format_article(payload)

    assert len(title) >= 5
    assert "Announcement" in title or "Update" in title
    assert canonical_url == "https://dxora.tech"


def test_format_article_truncates_overly_long_title(devto_adapter: DevtoAdapter):
    """Verify generated title does not exceed 120 characters."""
    long_text = "A" * 150 + ". https://example.com"
    payload = PlatformPostPayload(content=long_text)
    title, _, _, _ = devto_adapter.format_article(payload)

    assert len(title) <= 120
    assert title.endswith("...")


# ---------------------------------------------------------------------------
# 3. Status Publishing & Genuinely Published Verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_article_success(devto_adapter: DevtoAdapter):
    """Verify successful article publication to DEV.to with canonical URL extraction."""
    mock_response = {
        "id": 987654,
        "title": "Automated Multi-Platform Posting Engine",
        "published": True,
        "url": "https://dev.to/dxoratech/automated-multi-platform-posting-engine-xyz",
        "canonical_url": "https://dxora.tech/blog/automated-posting",
    }

    route = respx.post("https://dev.to/api/articles").respond(
        status_code=201,
        json=mock_response,
    )

    payload = PlatformPostPayload(
        title="Automated Multi-Platform Posting Engine",
        content="Scale your reach effortlessly across web ecosystems! https://dxora.tech/blog/automated-posting #devops",
    )

    result = await devto_adapter.publish(payload)

    # 1. Verify PublishResult
    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.platform == PlatformType.DEVTO
    assert result.external_post_id == "987654"
    # Canonical URL extracted
    assert result.external_url == "https://dxora.tech/blog/automated-posting"
    assert result.latency_ms > 0

    # 2. Verify wire request headers and payload
    assert route.called
    sent_req = route.calls.last.request
    assert sent_req.headers.get("api-key") == "devto_test_secret_api_key_12345"
    assert sent_req.headers.get("Accept") == "application/vnd.forem.api-v1+json"
    assert sent_req.headers.get("Content-Type") == "application/json"

    sent_body = sent_req.read().decode("utf-8")
    assert '"published":true' in sent_body or '"published": true' in sent_body
    assert "https://dxora.tech/blog/automated-posting" in sent_body
    assert "Automated Multi-Platform Posting Engine" in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_publish_rejects_draft_publication(devto_adapter: DevtoAdapter):
    """Verify critical requirement: Do not claim that a draft is a successful publication.

    If DEV.to creates the record but published=False, the adapter must raise
    PlatformContentValidationError.
    """
    mock_draft_response = {
        "id": 987655,
        "title": "Accidental Draft",
        "published": False,  # Draft instead of published!
        "url": "https://dev.to/dxoratech/accidental-draft-preview",
    }

    respx.post("https://dev.to/api/articles").respond(
        status_code=201,
        json=mock_draft_response,
    )

    payload = PlatformPostPayload(content="Testing draft rejection enforcement. https://example.com")

    with pytest.raises(PlatformContentValidationError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 422
    assert "saved as a draft (published=false)" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_canonical_url_falls_back_to_live_url(devto_adapter: DevtoAdapter):
    """Verify external_url falls back to DEV.to web url when canonical_url is absent."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=201,
        json={
            "id": 123456,
            "title": "Post Without External Canonical",
            "published": True,
            "canonical_url": None,
            "url": "https://dev.to/dxoratech/post-without-external-canonical-123",
        },
    )

    payload = PlatformPostPayload(content="Internal post announcement.")
    result = await devto_adapter.publish(payload)

    assert result.success is True
    assert result.external_url == "https://dev.to/dxoratech/post-without-external-canonical-123"


# ---------------------------------------------------------------------------
# 4. Error Handling Tests (401, 403, 422, 429, 500, Network Timeout)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_auth_error_401(devto_adapter: DevtoAdapter):
    """Verify HTTP 401 raises PlatformAuthenticationError with retryable=False."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=401,
        json={"error": "unauthorized", "message": "Invalid API key"},
    )

    payload = PlatformPostPayload(content="Auth test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 401
    assert "Invalid API key" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_forbidden_error_403(devto_adapter: DevtoAdapter):
    """Verify HTTP 403 raises PlatformAuthenticationError."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=403,
        json={"error": "forbidden", "message": "API key lacks required write permissions"},
    )

    payload = PlatformPostPayload(content="Forbidden test")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_publish_validation_error_422(devto_adapter: DevtoAdapter):
    """Verify HTTP 422 raises PlatformContentValidationError with retryable=False."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=422,
        json={"error": "Unprocessable Entity", "message": "Tags can only contain up to 4 items"},
    )

    payload = PlatformPostPayload(content="Validation failure test")
    with pytest.raises(PlatformContentValidationError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 422
    assert "Tags can only contain up to 4 items" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_rate_limit_error_429(devto_adapter: DevtoAdapter):
    """Verify HTTP 429 raises PlatformRateLimitError with parsed Retry-After header."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=429,
        headers={"Retry-After": "45"},
        json={"error": "Rate limit exceeded"},
    )

    payload = PlatformPostPayload(content="Rate limit test")
    with pytest.raises(PlatformRateLimitError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 45.0


@pytest.mark.asyncio
@respx.mock
async def test_publish_server_error_500(devto_adapter: DevtoAdapter):
    """Verify HTTP 500 raises PlatformServerError with retryable=True."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=500,
        text="Internal Server Error in DEV.to cluster",
    )

    payload = PlatformPostPayload(content="Server error test")
    with pytest.raises(PlatformServerError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
@respx.mock
async def test_publish_network_timeout(devto_adapter: DevtoAdapter):
    """Verify connection timeout raises PlatformNetworkError with retryable=True."""
    respx.post("https://dev.to/api/articles").mock(
        side_effect=httpx.ConnectTimeout("Connection timed out to dev.to")
    )

    payload = PlatformPostPayload(content="Network drop test")
    with pytest.raises(PlatformNetworkError) as exc_info:
        await devto_adapter.publish(payload)

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_execute_safe_publish_converts_error_to_failure(devto_adapter: DevtoAdapter):
    """Verify execute_safe_publish traps exceptions and returns PublishFailure."""
    respx.post("https://dev.to/api/articles").respond(
        status_code=401,
        json={"error": "Unauthorized", "message": "Bad API key"},
    )

    payload = PlatformPostPayload(content="Safe publish test")
    failure = await devto_adapter.execute_safe_publish(payload)

    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.platform == PlatformType.DEVTO
    assert failure.error_type == "PlatformAuthenticationError"
    assert failure.retryable is False
    assert failure.status_code == 401


# ---------------------------------------------------------------------------
# 5. Health Diagnostics Tests (GET /api/users/me)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_devto_health_check_healthy(devto_adapter: DevtoAdapter):
    """Verify health check returns PlatformHealthResult with is_healthy=True."""
    respx.get("https://dev.to/api/users/me").respond(
        status_code=200,
        json={
            "type_of": "user",
            "id": 54321,
            "username": "dxoratech",
            "name": "Dxora Technologies",
        },
    )

    health = await devto_adapter.check_health()
    assert health.is_healthy is True
    assert health.is_configured is True
    assert "@dxoratech" in health.details
    assert health.latency_ms is not None


@pytest.mark.asyncio
async def test_devto_health_check_unconfigured():
    """Verify health check returns unconfigured status when API key is missing."""
    empty_settings = Settings(DEVTO_API_KEY=None)
    adapter = DevtoAdapter(settings=empty_settings)

    health = await adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is False
    assert "not configured" in health.details


@pytest.mark.asyncio
@respx.mock
async def test_devto_health_check_auth_failure(devto_adapter: DevtoAdapter):
    """Verify health check detects invalid API key (HTTP 401)."""
    respx.get("https://dev.to/api/users/me").respond(
        status_code=401,
        json={"error": "unauthorized"},
    )

    health = await devto_adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is True
    assert "401" in health.details
