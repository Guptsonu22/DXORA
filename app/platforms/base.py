"""Abstract platform base adapter and schemas."""

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformError,
    PlatformNetworkError,
    PlatformRateLimitError,
    PlatformServerError,
    PlatformUnconfiguredError,
)
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PlatformValidationResult,
    PublishFailure,
    PublishResult,
)

__all__ = [
    "BasePlatformAdapter",
    "PlatformAuthenticationError",
    "PlatformContentValidationError",
    "PlatformError",
    "PlatformHealthResult",
    "PlatformNetworkError",
    "PlatformPostPayload",
    "PlatformRateLimitError",
    "PlatformServerError",
    "PlatformUnconfiguredError",
    "PlatformValidationResult",
    "PublishFailure",
    "PublishResult",
]
