"""Abstract Platform Adapter defining the standardized contract for all networks."""

import time
from abc import ABC, abstractmethod

import httpx

from autopost_nexus.adapters.exceptions import (
    PlatformError,
    mask_sensitive_string,
)
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PlatformValidationResult,
    PublishFailure,
    PublishResult,
)
from autopost_nexus.config import Settings, get_settings
from autopost_nexus.schemas.posting import PlatformType


class BasePlatformAdapter(ABC):
    """Abstract Base Class specifying the interface contract for all social & messaging adapters.

    Every concrete platform adapter (Twitter, LinkedIn, Telegram, Discord, Reddit)
    must inherit from this base class and implement the abstract methods.
    """

    def __init__(self, settings: Settings | None = None, timeout_seconds: float = 10.0):
        self.settings = settings or get_settings()
        self.timeout_seconds = timeout_seconds

    # -----------------------------------------------------------------------
    # Abstract Properties & Methods (Contract)
    # -----------------------------------------------------------------------

    @property
    @abstractmethod
    def platform_type(self) -> PlatformType:
        """Return the PlatformType enum associated with this adapter."""

    @property
    @abstractmethod
    def max_characters(self) -> int:
        """Return the maximum allowed plain character length for this platform."""

    @property
    @abstractmethod
    def auth_mode(self) -> str:
        """Human-readable description of authentication mechanism used (e.g. OAuth 1.0a)."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if all necessary credentials for this platform are present."""

    @abstractmethod
    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Publish payload to the remote platform API.

        Raises:
            PlatformError (or a subclass) if the remote operation fails.
        """

    @abstractmethod
    async def check_health(self) -> PlatformHealthResult:
        """Verify credential validity and remote API reachability."""

    # -----------------------------------------------------------------------
    # Default Content Validation Implementation (Can be extended by adapters)
    # -----------------------------------------------------------------------

    def validate_content(self, payload: PlatformPostPayload) -> PlatformValidationResult:
        """Perform pre-flight sanity checks on content length and required fields."""
        errors: list[str] = []
        warnings: list[str] = []

        content_len = len(payload.content)
        if content_len == 0 or not payload.content.strip():
            errors.append("Content cannot be empty or whitespace only.")

        if content_len > self.max_characters:
            errors.append(
                f"Content exceeds {self.platform_type.value} limit of {self.max_characters} "
                f"characters (received {content_len})."
            )

        # Non-blocking warnings for high character utilization
        if content_len > (self.max_characters * 0.9) and content_len <= self.max_characters:
            warnings.append(
                f"Content utilizes over 90% of {self.platform_type.value} limit "
                f"({content_len}/{self.max_characters})."
            )

        return PlatformValidationResult(
            is_valid=len(errors) == 0,
            platform=self.platform_type,
            character_count=content_len,
            max_characters=self.max_characters,
            errors=errors,
            warnings=warnings,
        )

    # -----------------------------------------------------------------------
    # Standardized Resilient Execution Wrapper
    # -----------------------------------------------------------------------

    async def execute_safe_publish(
        self,
        payload: PlatformPostPayload,
    ) -> PublishResult | PublishFailure:
        """Execute publication with standardized error trapping and latency instrumentation.

        Guarantees that unhandled exceptions are converted into a standardized
        PublishFailure without raising uncaught errors to the caller.
        """
        start = time.perf_counter()

        # Pre-flight configuration check
        if not self.is_configured():
            latency = (time.perf_counter() - start) * 1000.0
            return PublishFailure(
                platform=self.platform_type,
                error_type="PlatformUnconfiguredError",
                error_message=f"Platform '{self.platform_type.value}' is not configured with valid credentials.",
                status_code=None,
                retryable=False,
                latency_ms=round(latency, 2),
            )

        # Pre-flight content validation check
        validation = self.validate_content(payload)
        if not validation.is_valid:
            latency = (time.perf_counter() - start) * 1000.0
            return PublishFailure(
                platform=self.platform_type,
                error_type="PlatformContentValidationError",
                error_message="; ".join(validation.errors),
                status_code=400,
                retryable=False,
                latency_ms=round(latency, 2),
            )

        try:
            result = await self.publish(payload)
            return result
        except PlatformError as exc:
            latency = (time.perf_counter() - start) * 1000.0
            retry_after = getattr(exc, "retry_after_seconds", None)
            return PublishFailure(
                platform=self.platform_type,
                error_type=exc.__class__.__name__,
                error_message=exc.message,
                status_code=exc.status_code,
                retryable=exc.retryable,
                retry_after_seconds=retry_after,
                latency_ms=round(latency, 2),
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return PublishFailure(
                platform=self.platform_type,
                error_type="PlatformNetworkError",
                error_message=f"Network connectivity error: {exc}",
                status_code=None,
                retryable=True,
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return PublishFailure(
                platform=self.platform_type,
                error_type="UnexpectedPlatformError",
                error_message=f"Unexpected error during {self.platform_type.value} dispatch: {exc}",
                status_code=None,
                retryable=False,
                latency_ms=round(latency, 2),
            )

    # -----------------------------------------------------------------------
    # HTTP Client Factory
    # -----------------------------------------------------------------------

    def get_http_client(self) -> httpx.AsyncClient:
        """Create a configured async HTTP client with connection limits and timeouts."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            headers={
                "User-Agent": f"AutoPostNexus/{self.settings.VERSION} (+https://github.com/Guptsonu22/DXORA)"
            },
            follow_redirects=True,
        )

    def mask(self, token: str | None) -> str:
        """Helper to mask sensitive tokens in logs and audits."""
        return mask_sensitive_string(token)
