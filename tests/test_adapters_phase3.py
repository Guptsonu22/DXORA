"""Comprehensive test suite for Phase 3: Abstract Platform Interface,

Standardized Response Schemas, Settings, and Common Error Handling.
"""

import httpx
import pytest
from pydantic import ValidationError

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformError,
    PlatformNetworkError,
    PlatformRateLimitError,
    PlatformServerError,
    PlatformUnconfiguredError,
    map_http_response_to_exception,
    mask_sensitive_string,
    parse_retry_after,
    sanitize_response_text,
)
from autopost_nexus.adapters.mock_adapter import MockPlatformAdapter
from autopost_nexus.adapters.registry import AdapterRegistry
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PlatformValidationResult,
    PublishFailure,
    PublishResult,
)
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType

# ---------------------------------------------------------------------------
# 1. Abstract Interface Contract Enforcement Tests
# ---------------------------------------------------------------------------


def test_cannot_instantiate_abstract_base_adapter():
    """Verify that BasePlatformAdapter cannot be instantiated directly."""
    with pytest.raises(TypeError) as excinfo:
        BasePlatformAdapter()  # type: ignore[abstract]
    assert "Can't instantiate abstract class BasePlatformAdapter" in str(excinfo.value)


def test_cannot_instantiate_incomplete_subclass():
    """Verify that a subclass missing abstract methods cannot be instantiated."""

    class IncompleteAdapter(BasePlatformAdapter):
        @property
        def platform_type(self) -> PlatformType:
            return PlatformType.TWITTER

    with pytest.raises(TypeError):
        IncompleteAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# 2. Standardized Response Schemas Tests
# ---------------------------------------------------------------------------


def test_publish_result_schema():
    """Verify PublishResult creation and immutability."""
    result = PublishResult(
        success=True,
        platform=PlatformType.TWITTER,
        external_post_id="tweet-998811",
        external_url="https://x.com/status/998811",
        latency_ms=142.5,
        raw_response={"id": "tweet-998811"},
    )
    assert result.success is True
    assert result.platform == PlatformType.TWITTER
    assert result.external_post_id == "tweet-998811"
    assert result.latency_ms == 142.5

    # Test frozen immutability
    with pytest.raises(ValidationError):
        result.success = False  # type: ignore[misc]


def test_publish_failure_schema():
    """Verify PublishFailure fields and serialization."""
    failure = PublishFailure(
        success=False,
        platform=PlatformType.LINKEDIN,
        error_type="PlatformRateLimitError",
        error_message="Rate limit reached",
        status_code=429,
        retryable=True,
        retry_after_seconds=30.0,
        latency_ms=210.0,
    )
    assert failure.success is False
    assert failure.platform == PlatformType.LINKEDIN
    assert failure.retryable is True
    assert failure.retry_after_seconds == 30.0


def test_platform_validation_result():
    """Verify PlatformValidationResult logic."""
    val = PlatformValidationResult(
        is_valid=True,
        platform=PlatformType.TELEGRAM,
        character_count=120,
        max_characters=4096,
        errors=[],
        warnings=["Utilizing under 10%"],
    )
    assert val.is_valid is True
    assert val.character_count == 120
    assert len(val.warnings) == 1


def test_platform_health_result():
    """Verify PlatformHealthResult schema."""
    health = PlatformHealthResult(
        platform=PlatformType.DISCORD,
        is_healthy=True,
        is_configured=True,
        auth_mode="Webhook URL",
        latency_ms=45.2,
        details="Webhook endpoint is active and valid.",
    )
    assert health.is_healthy is True
    assert health.platform == PlatformType.DISCORD
    assert health.auth_mode == "Webhook URL"


# ---------------------------------------------------------------------------
# 3. Common Error Handling & Exception Taxonomy Tests
# ---------------------------------------------------------------------------


def test_platform_error_taxonomy():
    """Verify base and derived platform exception properties."""
    base_err = PlatformError(
        platform=PlatformType.REDDIT,
        message="Generic failure",
        status_code=500,
        retryable=True,
    )
    assert base_err.platform == PlatformType.REDDIT
    assert base_err.retryable is True
    d = base_err.to_dict()
    assert d["platform"] == "reddit"
    assert d["error_type"] == "PlatformError"


def test_platform_authentication_error_is_not_retryable():
    """Authentication errors should never be retried automatically."""
    err = PlatformAuthenticationError(
        platform=PlatformType.TWITTER,
        message="Invalid Bearer Token",
    )
    assert err.retryable is False
    assert err.status_code == 401


def test_platform_rate_limit_error_is_retryable_with_cooldown():
    """Rate limit errors should be marked retryable and store cooldown."""
    err = PlatformRateLimitError(
        platform=PlatformType.TWITTER,
        message="Too Many Requests",
        retry_after_seconds=45.0,
    )
    assert err.retryable is True
    assert err.retry_after_seconds == 45.0
    assert err.to_dict()["retry_after_seconds"] == 45.0


def test_platform_network_error_is_retryable():
    """Network connection errors are transient and must be retryable."""
    err = PlatformNetworkError(
        platform=PlatformType.DISCORD,
        message="ConnectTimeout to discord.com",
    )
    assert err.retryable is True
    assert err.status_code is None


def test_map_http_response_401_to_authentication_error():
    """Verify HTTP 401 mapping."""
    request = httpx.Request("POST", "https://api.twitter.com/2/tweets")
    response = httpx.Response(401, request=request, text="Unauthorized: Invalid token")
    exc = map_http_response_to_exception(PlatformType.TWITTER, response)
    assert isinstance(exc, PlatformAuthenticationError)
    assert exc.retryable is False
    assert exc.status_code == 401


def test_map_http_response_429_to_rate_limit_error():
    """Verify HTTP 429 mapping and Retry-After header parsing."""
    request = httpx.Request("POST", "https://api.linkedin.com/v2/ugcPosts")
    response = httpx.Response(
        429,
        request=request,
        headers={"Retry-After": "35"},
        text="Rate limit exceeded",
    )
    exc = map_http_response_to_exception(PlatformType.LINKEDIN, response)
    assert isinstance(exc, PlatformRateLimitError)
    assert exc.retryable is True
    assert exc.retry_after_seconds == 35.0


def test_map_http_response_503_to_server_error():
    """Verify HTTP 503 mapping."""
    request = httpx.Request("POST", "https://api.telegram.org/bot123/sendMessage")
    response = httpx.Response(503, request=request, text="Service Unavailable")
    exc = map_http_response_to_exception(PlatformType.TELEGRAM, response)
    assert isinstance(exc, PlatformServerError)
    assert exc.retryable is True
    assert exc.status_code == 503


# ---------------------------------------------------------------------------
# 4. Secret Masking & Sanitization Tests
# ---------------------------------------------------------------------------


def test_mask_sensitive_string():
    """Verify sensitive token redaction helper."""
    assert mask_sensitive_string(None) == "None"
    assert mask_sensitive_string("") == "None"
    assert mask_sensitive_string("short") == "********"
    # Long token: keeps 4 prefix and 4 suffix
    masked = mask_sensitive_string("ghp_1234567890abcdef1234567890abcdef")
    assert masked.startswith("ghp_")
    assert masked.endswith("cdef")
    assert "..." in masked
    assert "1234567890" not in masked


def test_sanitize_response_text_redacts_bearer():
    """Verify Bearer token redaction from raw server responses."""
    raw = "Error authenticating with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123"
    sanitized = sanitize_response_text(raw)
    assert "Bearer [REDACTED]" in sanitized
    assert "eyJhbGciOi" not in sanitized


def test_parse_retry_after():
    """Verify Retry-After header parsing."""
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(None, default_cooldown=60.0) == 60.0
    assert parse_retry_after("invalid-date", default_cooldown=45.0) == 45.0
    assert parse_retry_after("0") == 1.0  # Min 1.0s safety floor


# ---------------------------------------------------------------------------
# 5. Settings & Platform Credentials Tests
# ---------------------------------------------------------------------------


def test_settings_platform_configuration_detection():
    """Verify Settings helper methods for platform configuration state."""
    custom_settings = Settings(
        TWITTER_API_KEY="test_key_1234567890",
        TWITTER_ACCESS_TOKEN="test_token_1234567890",
        TELEGRAM_BOT_TOKEN=None,
    )
    assert custom_settings.is_platform_configured("twitter") is True
    assert custom_settings.is_platform_configured("telegram") is False
    assert custom_settings.is_platform_configured("discord") is False

    masked = custom_settings.get_masked_credentials()
    assert masked["twitter"]["configured"] is True
    assert "..." in str(masked["twitter"]["api_key"])
    assert masked["telegram"]["configured"] is False


# ---------------------------------------------------------------------------
# 6. Base Adapter Safe Publish Execution Tests (Using Mock Adapter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_publish_success():
    """Verify execute_safe_publish returns PublishResult on success."""
    adapter = MockPlatformAdapter(platform=PlatformType.TWITTER)
    payload = PlatformPostPayload(content="Valid tweet under 280 characters.")

    result = await adapter.execute_safe_publish(payload)
    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.platform == PlatformType.TWITTER
    assert "mock-twitter" in result.external_post_id
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_safe_publish_catches_auth_error():
    """Verify execute_safe_publish returns PublishFailure on 401 auth error."""
    adapter = MockPlatformAdapter(
        platform=PlatformType.TWITTER,
        simulate_error="auth",
    )
    payload = PlatformPostPayload(content="Test content")

    failure = await adapter.execute_safe_publish(payload)
    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.error_type == "PlatformAuthenticationError"
    assert failure.retryable is False
    assert failure.status_code == 401


@pytest.mark.asyncio
async def test_safe_publish_catches_rate_limit_error():
    """Verify execute_safe_publish returns PublishFailure with retry cooldown on 429."""
    adapter = MockPlatformAdapter(
        platform=PlatformType.LINKEDIN,
        simulate_error="rate_limit",
        retry_after=50.0,
    )
    payload = PlatformPostPayload(content="LinkedIn content")

    failure = await adapter.execute_safe_publish(payload)
    assert isinstance(failure, PublishFailure)
    assert failure.success is False
    assert failure.error_type == "PlatformRateLimitError"
    assert failure.retryable is True
    assert failure.retry_after_seconds == 50.0


@pytest.mark.asyncio
async def test_safe_publish_blocks_unconfigured_platform():
    """Verify execute_safe_publish intercepts unconfigured platform without network call."""
    adapter = MockPlatformAdapter(
        platform=PlatformType.DISCORD,
        configured=False,
    )
    payload = PlatformPostPayload(content="Discord message")

    failure = await adapter.execute_safe_publish(payload)
    assert isinstance(failure, PublishFailure)
    assert failure.error_type == "PlatformUnconfiguredError"
    assert failure.retryable is False


@pytest.mark.asyncio
async def test_safe_publish_blocks_content_exceeding_character_limit():
    """Verify execute_safe_publish validates content limit before dispatch."""
    adapter = MockPlatformAdapter(
        platform=PlatformType.TWITTER,
        max_chars=280,
    )
    payload = PlatformPostPayload(content="X" * 285)

    failure = await adapter.execute_safe_publish(payload)
    assert isinstance(failure, PublishFailure)
    assert failure.error_type == "PlatformContentValidationError"
    assert "exceeds twitter limit of 280 characters" in failure.error_message.lower()


# ---------------------------------------------------------------------------
# 7. Adapter Registry Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_registry_lifecycle():
    """Verify registering, retrieving, and checking health of adapters."""
    registry = AdapterRegistry()
    assert len(registry.list_platforms()) == 0

    twitter_adapter = MockPlatformAdapter(platform=PlatformType.TWITTER)
    telegram_adapter = MockPlatformAdapter(platform=PlatformType.TELEGRAM)

    registry.register(twitter_adapter)
    registry.register(telegram_adapter)

    assert registry.has(PlatformType.TWITTER) is True
    assert registry.has(PlatformType.TELEGRAM) is True
    assert registry.has(PlatformType.DISCORD) is False

    retrieved = registry.get(PlatformType.TWITTER)
    assert retrieved == twitter_adapter

    # Requesting unregistered platform raises error
    with pytest.raises(PlatformUnconfiguredError):
        registry.get(PlatformType.DISCORD)

    # Health check across registered adapters
    health_results = await registry.check_all_health()
    assert len(health_results) == 2
    assert health_results[PlatformType.TWITTER].is_healthy is True
    assert health_results[PlatformType.TELEGRAM].is_healthy is True
