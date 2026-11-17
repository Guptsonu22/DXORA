"""Registry managing adapter instances and dynamic dispatch resolution."""

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.exceptions import PlatformUnconfiguredError
from autopost_nexus.adapters.schemas import PlatformHealthResult
from autopost_nexus.schemas.posting import PlatformType


class AdapterRegistry:
    """Registry maintaining initialized platform adapter instances."""

    def __init__(self):
        self._adapters: dict[PlatformType, BasePlatformAdapter] = {}

    def register(self, adapter: BasePlatformAdapter) -> None:
        """Register a platform adapter instance."""
        self._adapters[adapter.platform_type] = adapter

    def get(self, platform: PlatformType) -> BasePlatformAdapter:
        """Retrieve the adapter for the requested platform.

        Raises:
            PlatformUnconfiguredError if no adapter has been registered for that platform.
        """
        if platform not in self._adapters:
            raise PlatformUnconfiguredError(platform)
        return self._adapters[platform]

    def has(self, platform: PlatformType) -> bool:
        """Check whether an adapter is registered for a platform."""
        return platform in self._adapters

    def list_platforms(self) -> list[PlatformType]:
        """Return list of all registered platform types."""
        return list(self._adapters.keys())

    async def check_all_health(self) -> dict[PlatformType, PlatformHealthResult]:
        """Run health checks across all registered platform adapters."""
        results: dict[PlatformType, PlatformHealthResult] = {}
        for platform, adapter in self._adapters.items():
            results[platform] = await adapter.check_health()
        return results

    def clear(self) -> None:
        """Clear all registered adapters (useful for test resets)."""
        self._adapters.clear()


# Default singleton registry instance
_default_registry: AdapterRegistry | None = None


def get_adapter_registry() -> AdapterRegistry:
    """Return or initialize global AdapterRegistry instance."""
    global _default_registry
    if _default_registry is None:
        _default_registry = AdapterRegistry()
    return _default_registry
