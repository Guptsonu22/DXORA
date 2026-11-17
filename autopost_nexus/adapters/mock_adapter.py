"""Configurable Mock Platform Adapter for testing contract conformity and failure modes."""

import time

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformNetworkError,
    PlatformRateLimitError,
    PlatformServerError,
)
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PublishResult,
)
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


class MockPlatformAdapter(BasePlatformAdapter):
    """Reference implementation of BasePlatformAdapter with configurable behavior for testing."""

    def __init__(
        self,
        platform: PlatformType = PlatformType.TWITTER,
        max_chars: int = 280,
        auth_mode_str: str = "Mock Authentication",
        configured: bool = True,
        simulate_error: str | None = None,
        retry_after: float | None = None,
        settings: Settings | None = None,
    ):
        super().__init__(settings=settings)
        self._platform_type = platform
        self._max_chars = max_chars
        self._auth_mode = auth_mode_str
        self._configured = configured
        self.simulate_error = simulate_error
        self.retry_after = retry_after
        self.published_payloads: list[PlatformPostPayload] = []

    @property
    def platform_type(self) -> PlatformType:
        return self._platform_type

    @property
    def max_characters(self) -> int:
        return self._max_chars

    @property
    def auth_mode(self) -> str:
        return self._auth_mode

    def is_configured(self) -> bool:
        return self._configured

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Simulate publishing with programmable failure triggers."""
        start = time.perf_counter()

        if self.simulate_error == "auth":
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message="Simulated authentication failure (HTTP 401)",
            )

        if self.simulate_error == "rate_limit":
            raise PlatformRateLimitError(
                platform=self.platform_type,
                message="Simulated rate limit exceeded (HTTP 429)",
                retry_after_seconds=self.retry_after or 45.0,
            )

        if self.simulate_error == "network":
            raise PlatformNetworkError(
                platform=self.platform_type,
                message="Simulated socket timeout / connection drop",
            )

        if self.simulate_error == "validation":
            raise PlatformContentValidationError(
                platform=self.platform_type,
                message="Simulated payload rejection (HTTP 400)",
            )

        if self.simulate_error == "server":
            raise PlatformServerError(
                platform=self.platform_type,
                message="Simulated 503 Service Unavailable",
                status_code=503,
            )

        # Successful publication simulation
        self.published_payloads.append(payload)
        latency = (time.perf_counter() - start) * 1000.0

        return PublishResult(
            success=True,
            platform=self.platform_type,
            external_post_id=f"mock-{self.platform_type.value}-12345",
            external_url=f"https://{self.platform_type.value}.com/posts/mock-12345",
            latency_ms=round(latency, 2),
            raw_response={"status": "ok", "mock": True},
        )

    async def check_health(self) -> PlatformHealthResult:
        """Simulate health check."""
        if not self.is_configured():
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=False,
                auth_mode=self.auth_mode,
                latency_ms=None,
                details="Platform is not configured.",
            )

        return PlatformHealthResult(
            platform=self.platform_type,
            is_healthy=True,
            is_configured=True,
            auth_mode=self.auth_mode,
            latency_ms=12.5,
            details="Mock connectivity verified successfully.",
        )
