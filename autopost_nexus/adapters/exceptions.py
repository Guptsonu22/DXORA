"""Unified error hierarchy and exception handling for platform integrations."""

import re
from typing import Any

import httpx

from autopost_nexus.schemas.posting import PlatformType


class PlatformError(Exception):
    """Base exception for all third-party platform integration failures."""

    def __init__(
        self,
        platform: PlatformType,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
        retryable: bool = False,
        raw_error: Any | None = None,
    ):
        super().__init__(f"[{platform.value.upper()}] {message}")
        self.platform = platform
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.retryable = retryable
        self.raw_error = raw_error

    def to_dict(self) -> dict[str, Any]:
        """Serialize error details for audit logging and API responses."""
        return {
            "platform": self.platform.value,
            "error_type": self.__class__.__name__,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "response_body_snippet": self.response_body[:500] if self.response_body else None,
        }


class PlatformAuthenticationError(PlatformError):
    """Raised when platform API credentials are missing, expired, or rejected (HTTP 401/403)."""

    def __init__(
        self,
        platform: PlatformType,
        message: str = "Authentication failed: invalid or expired credentials",
        status_code: int | None = 401,
        response_body: str | None = None,
    ):
        super().__init__(
            platform=platform,
            message=message,
            status_code=status_code,
            response_body=response_body,
            retryable=False,  # Bad credentials cannot succeed without configuration change
        )


class PlatformRateLimitError(PlatformError):
    """Raised when platform rate limit or quota ceiling is hit (HTTP 429)."""

    def __init__(
        self,
        platform: PlatformType,
        message: str = "Rate limit exceeded",
        status_code: int = 429,
        response_body: str | None = None,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(
            platform=platform,
            message=message,
            status_code=status_code,
            response_body=response_body,
            retryable=True,  # Rate limits are transient; safe to retry after cooldown
        )
        self.retry_after_seconds = retry_after_seconds

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["retry_after_seconds"] = self.retry_after_seconds
        return data


class PlatformNetworkError(PlatformError):
    """Raised on connection timeouts, DNS resolution failures, or dropped sockets."""

    def __init__(
        self,
        platform: PlatformType,
        message: str = "Network connectivity failure or socket timeout",
        raw_error: Any | None = None,
    ):
        super().__init__(
            platform=platform,
            message=message,
            status_code=None,
            retryable=True,  # Transient network blips should be retried with backoff
            raw_error=raw_error,
        )


class PlatformContentValidationError(PlatformError):
    """Raised when post content violates platform-specific schemas or formatting rules."""

    def __init__(
        self,
        platform: PlatformType,
        message: str,
        response_body: str | None = None,
    ):
        super().__init__(
            platform=platform,
            message=message,
            status_code=400,
            response_body=response_body,
            retryable=False,  # Content must be edited by user before re-attempting
        )


class PlatformServerError(PlatformError):
    """Raised when remote platform returns a 5xx internal server error."""

    def __init__(
        self,
        platform: PlatformType,
        message: str = "Remote platform encountered an internal server error",
        status_code: int = 500,
        response_body: str | None = None,
    ):
        super().__init__(
            platform=platform,
            message=message,
            status_code=status_code,
            response_body=response_body,
            retryable=True,  # Remote server errors (500/502/503/504) are transient
        )


class PlatformUnconfiguredError(PlatformError):
    """Raised when an operation is requested on an unconfigured platform."""

    def __init__(self, platform: PlatformType):
        super().__init__(
            platform=platform,
            message=f"Platform credentials for '{platform.value}' are not configured in environment.",
            status_code=None,
            retryable=False,
        )


# ---------------------------------------------------------------------------
# Utility Helpers for HTTP Error Parsing and Secret Redaction
# ---------------------------------------------------------------------------


def mask_sensitive_string(val: str | None, visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    """Mask a secret token while keeping small prefix/suffix for identification."""
    if not val:
        return "None"
    if len(val) <= (visible_prefix + visible_suffix + 2):
        return "********"
    return f"{val[:visible_prefix]}...{val[-visible_suffix:]}"


def sanitize_response_text(text: str | None) -> str:
    """Strip access tokens or secrets that might appear in raw response bodies."""
    if not text:
        return ""
    # Redact common bearer tokens, client secrets, and api keys
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED]", text)
    sanitized = re.sub(
        r"(access_token|client_secret|token)=([A-Za-z0-9\-._~+/]+)", r"\1=[REDACTED]", sanitized
    )
    return sanitized


def parse_retry_after(header_val: str | None, default_cooldown: float = 60.0) -> float:
    """Parse HTTP Retry-After header into seconds."""
    if not header_val:
        return default_cooldown
    try:
        # Standard integer seconds
        val = float(header_val.strip())
        return max(val, 1.0)
    except ValueError:
        # Fall back to default cooldown if HTTP-date or unrecognized format
        return default_cooldown


def map_http_response_to_exception(
    platform: PlatformType,
    response: httpx.Response,
) -> PlatformError:
    """Map an HTTP response with non-2xx status to an appropriate PlatformError subclass."""
    code = response.status_code
    body = sanitize_response_text(response.text)

    if code in (401, 403):
        return PlatformAuthenticationError(
            platform=platform,
            message=f"Authentication failed with status HTTP {code}: {body[:200]}",
            status_code=code,
            response_body=body,
        )

    if code == 429:
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        return PlatformRateLimitError(
            platform=platform,
            message=f"Rate limit exceeded (HTTP 429). Retry after {retry_after}s: {body[:200]}",
            status_code=429,
            response_body=body,
            retry_after_seconds=retry_after,
        )

    if code in (400, 422):
        return PlatformContentValidationError(
            platform=platform,
            message=f"Payload rejected by platform (HTTP {code}): {body[:200]}",
            response_body=body,
        )

    if code >= 500:
        return PlatformServerError(
            platform=platform,
            message=f"Remote server error (HTTP {code}): {body[:200]}",
            status_code=code,
            response_body=body,
        )

    return PlatformError(
        platform=platform,
        message=f"Unexpected platform response (HTTP {code}): {body[:200]}",
        status_code=code,
        response_body=body,
        retryable=False,
    )
