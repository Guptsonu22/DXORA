"""Adapters module exports."""

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.bluesky import BlueskyAdapter
from autopost_nexus.adapters.devto import DevtoAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformError,
    PlatformNetworkError,
    PlatformRateLimitError,
    PlatformServerError,
    PlatformUnconfiguredError,
    map_http_response_to_exception,
    mask_sensitive_string,
    parse_retry_after,
)
from autopost_nexus.adapters.mastodon import MastodonAdapter
from autopost_nexus.adapters.mock_adapter import MockPlatformAdapter
from autopost_nexus.adapters.registry import AdapterRegistry, get_adapter_registry
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PlatformValidationResult,
    PublishFailure,
    PublishResult,
)
from autopost_nexus.adapters.wordpress import WordPressAdapter

__all__ = [
    "AdapterRegistry",
    "BasePlatformAdapter",
    "BlueskyAdapter",
    "DevtoAdapter",
    "MastodonAdapter",
    "MockPlatformAdapter",
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
    "WordPressAdapter",
    "get_adapter_registry",
    "map_http_response_to_exception",
    "mask_sensitive_string",
    "parse_retry_after",
]
