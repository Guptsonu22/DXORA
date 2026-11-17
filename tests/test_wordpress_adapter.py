"""Comprehensive test suite for Phase 7: Official WordPress REST API Adapter.

Validates:
- Application Password authentication via HTTP Basic Auth
- Published posts creation via POST /wp-json/wp/v2/posts
- Meaningful title and HTML body generation from short messages
- Enforcement of status="publish" and rejection of non-published statuses
- Actual permalink extraction from post entity
- Credential errors (401/403) and validation errors (400/422)
- Server errors (500/503) and inaccessible site handling (ConnectTimeout)
- Health diagnostics via GET /wp-json/wp/v2/users/me
"""

import base64

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
from autopost_nexus.adapters.wordpress import WordPressAdapter
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


@pytest.fixture
def wp_settings() -> Settings:
    """Provide Settings configured with test WordPress credentials."""
    return Settings(
        WORDPRESS_SITE_URL="https://myblog.example.com",
        WORDPRESS_USERNAME="wp_editor",
        WORDPRESS_APP_PASSWORD="abcd efgh ijkl mnop qrst uvwx",
    )


@pytest.fixture
def wp_adapter(wp_settings: Settings) -> WordPressAdapter:
    """Provide configured WordPressAdapter instance."""
    return WordPressAdapter(settings=wp_settings)


# ---------------------------------------------------------------------------
# 1. Properties & Configuration Tests
# ---------------------------------------------------------------------------


def test_wordpress_adapter_properties(wp_adapter: WordPressAdapter):
    """Verify standard properties conforming to BasePlatformAdapter."""
    assert wp_adapter.platform_type == PlatformType.WORDPRESS
    assert wp_adapter.max_characters == 65536
    assert "Application Password" in wp_adapter.auth_mode
    assert wp_adapter.is_configured() is True
    assert wp_adapter.site_url == "https://myblog.example.com"
    assert wp_adapter.api_base == "https://myblog.example.com/wp-json/wp/v2"


def test_wordpress_site_url_normalization():
    """Verify that trailing slashes and nested /wp-json paths are normalized."""
    s1 = Settings(
        WORDPRESS_SITE_URL="https://demo.wordpress.org/",
        WORDPRESS_USERNAME="user",
        WORDPRESS_APP_PASSWORD="pwd",
    )
    assert WordPressAdapter(settings=s1).site_url == "https://demo.wordpress.org"
    assert WordPressAdapter(settings=s1).api_base == "https://demo.wordpress.org/wp-json/wp/v2"

    s2 = Settings(
        WORDPRESS_SITE_URL="https://demo.wordpress.org/wp-json",
        WORDPRESS_USERNAME="user",
        WORDPRESS_APP_PASSWORD="pwd",
    )
    assert WordPressAdapter(settings=s2).site_url == "https://demo.wordpress.org"

    s3 = Settings(
        WORDPRESS_SITE_URL="https://demo.wordpress.org/wp-json/wp/v2/",
        WORDPRESS_USERNAME="user",
        WORDPRESS_APP_PASSWORD="pwd",
    )
    assert WordPressAdapter(settings=s3).site_url == "https://demo.wordpress.org"


def test_wordpress_unconfigured_detection():
    """Verify is_configured returns False when any required credential is missing."""
    empty1 = Settings(WORDPRESS_SITE_URL=None, WORDPRESS_USERNAME="u", WORDPRESS_APP_PASSWORD="p")
    assert WordPressAdapter(settings=empty1).is_configured() is False

    empty2 = Settings(WORDPRESS_SITE_URL="https://site.com", WORDPRESS_USERNAME=None, WORDPRESS_APP_PASSWORD="p")
    assert WordPressAdapter(settings=empty2).is_configured() is False

    empty3 = Settings(WORDPRESS_SITE_URL="https://site.com", WORDPRESS_USERNAME="u", WORDPRESS_APP_PASSWORD=None)
    assert WordPressAdapter(settings=empty3).is_configured() is False


def test_wordpress_basic_auth_header_construction(wp_adapter: WordPressAdapter):
    """Verify HTTP Basic Auth header encodes username and spaced Application Password correctly."""
    header = wp_adapter.get_auth_header()
    assert "Authorization" in header
    assert header["Authorization"].startswith("Basic ")

    encoded = header["Authorization"].split(" ")[1]
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded == "wp_editor:abcd efgh ijkl mnop qrst uvwx"


# ---------------------------------------------------------------------------
# 2. Content Formatting: Title and HTML Content Generation
# ---------------------------------------------------------------------------


def test_format_post_explicit_title(wp_adapter: WordPressAdapter):
    """Verify explicit title is preserved and content is wrapped in paragraph tag."""
    payload = PlatformPostPayload(
        title="Custom WordPress Article Headline",
        content="Here is the detailed announcement regarding our system launch. https://example.com",
    )
    title, content = wp_adapter.format_post(payload)

    assert title == "Custom WordPress Article Headline"
    assert content == "<p>Here is the detailed announcement regarding our system launch. https://example.com</p>"


def test_format_post_auto_generates_meaningful_title_from_message(wp_adapter: WordPressAdapter):
    """Verify first clause of short message is transformed into an appropriate post title."""
    payload = PlatformPostPayload(
        content="Check out our latest business platform and grow your online visibility. https://example.com",
    )
    title, content = wp_adapter.format_post(payload)

    assert "Check out our latest business platform" in title
    assert "https://" not in title
    assert "<p>Check out our latest business platform" in content


def test_format_post_fallback_title_for_url_only_message(wp_adapter: WordPressAdapter):
    """Verify clean fallback title when message only contains a URL."""
    payload = PlatformPostPayload(content="https://dxora.tech")
    title, content = wp_adapter.format_post(payload)

    assert len(title) >= 5
    assert "Announcement" in title or "Update" in title
    assert "<p>https://dxora.tech</p>" in content


def test_format_post_truncates_overly_long_title(wp_adapter: WordPressAdapter):
    """Verify title does not exceed 120 characters."""
    long_msg = "W" * 150 + ". https://example.com"
    payload = PlatformPostPayload(content=long_msg)
    title, _ = wp_adapter.format_post(payload)

    assert len(title) <= 120
    assert title.endswith("...")


# ---------------------------------------------------------------------------
# 3. Status Publishing & Permalink Extraction Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_post_success_with_permalink(wp_adapter: WordPressAdapter):
    """Verify successful post publication to WordPress and extraction of actual permalink."""
    mock_post_response = {
        "id": 4059,
        "date": "2026-11-17T17:15:00",
        "status": "publish",
        "type": "post",
        "link": "https://myblog.example.com/2026/11/17/latest-business-platform/",
        "title": {"rendered": "Check out our latest business platform"},
        "content": {"rendered": "<p>Check out our latest business platform and grow...</p>"},
        "guid": {"rendered": "https://myblog.example.com/?p=4059"},
    }

    route = respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=201,
        json=mock_post_response,
    )

    payload = PlatformPostPayload(
        content="Check out our latest business platform and grow your online visibility. https://example.com",
    )

    result = await wp_adapter.publish(payload)

    # 1. Verify PublishResult
    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.platform == PlatformType.WORDPRESS
    assert result.external_post_id == "4059"
    # Actual permalink extracted
    assert result.external_url == "https://myblog.example.com/2026/11/17/latest-business-platform/"
    assert result.latency_ms > 0

    # 2. Verify wire request
    assert route.called
    sent_req = route.calls.last.request
    assert "Basic " in sent_req.headers.get("Authorization", "")
    assert sent_req.headers.get("Content-Type") == "application/json"

    sent_body = sent_req.read().decode("utf-8")
    assert '"status":"publish"' in sent_body or '"status": "publish"' in sent_body
    assert "Check out our latest business platform" in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_publish_rejects_non_published_status(wp_adapter: WordPressAdapter):
    """Verify that a post created as draft or pending raises PlatformContentValidationError."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=201,
        json={
            "id": 4060,
            "status": "draft",  # Draft status returned by server
            "link": "https://myblog.example.com/?p=4060&preview=true",
        },
    )

    payload = PlatformPostPayload(content="Draft test announcement. https://example.com")

    with pytest.raises(PlatformContentValidationError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 422
    assert "status 'draft' instead of 'publish'" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_permalink_guid_fallback(wp_adapter: WordPressAdapter):
    """Verify permalink fallback to guid.rendered when link attribute is absent."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=201,
        json={
            "id": 4061,
            "status": "publish",
            "link": None,
            "guid": {"rendered": "https://myblog.example.com/?p=4061"},
        },
    )

    payload = PlatformPostPayload(content="Guid permalink fallback test. https://example.com")
    result = await wp_adapter.publish(payload)

    assert result.success is True
    assert result.external_url == "https://myblog.example.com/?p=4061"


# ---------------------------------------------------------------------------
# 4. Error Handling: Auth, Validation, Rate Limit & Inaccessible Sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_auth_error_401(wp_adapter: WordPressAdapter):
    """Verify HTTP 401 raises PlatformAuthenticationError with non-retryable flag."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=401,
        json={
            "code": "rest_not_logged_in",
            "message": "You are not currently logged in.",
            "data": {"status": 401},
        },
    )

    payload = PlatformPostPayload(content="Auth failure test. https://example.com")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 401
    assert "You are not currently logged in" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_forbidden_error_403(wp_adapter: WordPressAdapter):
    """Verify HTTP 403 raises PlatformAuthenticationError."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=403,
        json={
            "code": "rest_cannot_create",
            "message": "Sorry, you are not allowed to create posts as this user.",
            "data": {"status": 403},
        },
    )

    payload = PlatformPostPayload(content="Forbidden test. https://example.com")
    with pytest.raises(PlatformAuthenticationError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 403
    assert "not allowed to create posts" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_validation_error_400(wp_adapter: WordPressAdapter):
    """Verify HTTP 400 raises PlatformContentValidationError with retryable=False."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=400,
        json={
            "code": "rest_invalid_param",
            "message": "Invalid parameter(s): title",
            "data": {"status": 400},
        },
    )

    payload = PlatformPostPayload(content="Invalid parameter test. https://example.com")
    with pytest.raises(PlatformContentValidationError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
    assert "Invalid parameter" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_publish_rate_limit_error_429(wp_adapter: WordPressAdapter):
    """Verify HTTP 429 raises PlatformRateLimitError with Retry-After header parsed."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=429,
        headers={"Retry-After": "60"},
        json={"code": "rest_rate_limit_exceeded", "message": "Rate limit reached"},
    )

    payload = PlatformPostPayload(content="Rate limit test. https://example.com")
    with pytest.raises(PlatformRateLimitError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 60.0


@pytest.mark.asyncio
@respx.mock
async def test_publish_server_error_500(wp_adapter: WordPressAdapter):
    """Verify HTTP 500 raises PlatformServerError with retryable=True."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=500,
        text="Internal Server Error: Database connection failed",
    )

    payload = PlatformPostPayload(content="Server error test. https://example.com")
    with pytest.raises(PlatformServerError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
@respx.mock
async def test_publish_inaccessible_site_connection_timeout(wp_adapter: WordPressAdapter):
    """Verify ConnectTimeout to WordPress site raises PlatformNetworkError with descriptive message."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").mock(
        side_effect=httpx.ConnectTimeout("Connection timed out to myblog.example.com")
    )

    payload = PlatformPostPayload(content="Inaccessible site test. https://example.com")
    with pytest.raises(PlatformNetworkError) as exc_info:
        await wp_adapter.publish(payload)

    assert exc_info.value.retryable is True
    assert "Inaccessible WordPress site at https://myblog.example.com" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_execute_safe_publish_converts_error_to_failure(wp_adapter: WordPressAdapter):
    """Verify execute_safe_publish traps exceptions and returns PublishFailure."""
    respx.post("https://myblog.example.com/wp-json/wp/v2/posts").respond(
        status_code=401,
        json={"code": "rest_not_logged_in", "message": "Bad Application Password"},
    )

    payload = PlatformPostPayload(content="Safe publish test. https://example.com")
    failure = await wp_adapter.execute_safe_publish(payload)

    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.platform == PlatformType.WORDPRESS
    assert failure.error_type == "PlatformAuthenticationError"
    assert failure.retryable is False
    assert failure.status_code == 401


# ---------------------------------------------------------------------------
# 5. Health Diagnostics Tests (GET /wp-json/wp/v2/users/me)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_wordpress_health_check_healthy(wp_adapter: WordPressAdapter):
    """Verify health check returns PlatformHealthResult with is_healthy=True."""
    respx.get("https://myblog.example.com/wp-json/wp/v2/users/me").respond(
        status_code=200,
        json={
            "id": 1,
            "name": "Site Editor",
            "slug": "wp_editor",
            "roles": ["editor", "administrator"],
        },
    )

    health = await wp_adapter.check_health()
    assert health.is_healthy is True
    assert health.is_configured is True
    assert "Site Editor" in health.details
    assert "@wp_editor" in health.details
    assert health.latency_ms is not None


@pytest.mark.asyncio
async def test_wordpress_health_check_unconfigured():
    """Verify health check returns unconfigured status when credentials are not configured."""
    empty_settings = Settings(
        WORDPRESS_SITE_URL=None,
        WORDPRESS_USERNAME=None,
        WORDPRESS_APP_PASSWORD=None,
    )
    adapter = WordPressAdapter(settings=empty_settings)

    health = await adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is False
    assert "not configured" in health.details


@pytest.mark.asyncio
@respx.mock
async def test_wordpress_health_check_auth_failure(wp_adapter: WordPressAdapter):
    """Verify health check detects invalid Application Password (HTTP 401)."""
    respx.get("https://myblog.example.com/wp-json/wp/v2/users/me").respond(
        status_code=401,
        json={"code": "rest_not_logged_in", "message": "You are not logged in."},
    )

    health = await wp_adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is True
    assert "401" in health.details


@pytest.mark.asyncio
@respx.mock
async def test_wordpress_health_check_inaccessible_site(wp_adapter: WordPressAdapter):
    """Verify health check detects inaccessible site host."""
    respx.get("https://myblog.example.com/wp-json/wp/v2/users/me").mock(
        side_effect=httpx.ConnectError("Could not resolve host myblog.example.com")
    )

    health = await wp_adapter.check_health()
    assert health.is_healthy is False
    assert health.is_configured is True
    assert "Inaccessible WordPress site" in health.details
