"""Central Multi-Platform Posting Service orchestrating concurrent broadcasting.

Strictly implements requirements from master prompt Part 1, Part 6, and Part 7:
- Internally registers all five required platforms: Bluesky, Mastodon, DEV.to, WordPress, Telegram.
- Executes platform publishing operations concurrently via asyncio.gather with return_exceptions=True.
- Wraps each platform in an isolated per-platform timeout.
- Isolates errors so failure or timeout on one platform never impacts or halts others.
- Formats individual platform results per Part 6 and aggregate summary per Part 7.
"""

import asyncio
import logging
from collections.abc import Sequence

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.bluesky import BlueskyAdapter
from autopost_nexus.adapters.devto import DevtoAdapter
from autopost_nexus.adapters.mastodon import MastodonAdapter
from autopost_nexus.adapters.schemas import PlatformPostPayload, PublishResult
from autopost_nexus.adapters.telegram import TelegramAdapter
from autopost_nexus.adapters.wordpress import WordPressAdapter
from autopost_nexus.config import Settings, get_settings
from autopost_nexus.schemas.posting import (
    PLATFORM_DISPLAY_NAMES,
    StandardPlatformResult,
    StandardPostingResponse,
    extract_platform_date_time,
)

logger = logging.getLogger(__name__)


class CentralPostingService:
    """Central coordinator for multi-platform broadcasting."""

    def __init__(
        self,
        settings: Settings | None = None,
        adapters: Sequence[BasePlatformAdapter] | None = None,
        per_platform_timeout: float = 10.0,
    ) -> None:
        """Initialize posting service with optional custom settings or adapter instances.

        Args:
            settings: Application configuration settings instance.
            adapters: Optional custom sequence of platform adapters (enables test dependency injection).
            per_platform_timeout: Max timeout in seconds allotted per platform before isolated abort.
        """
        self.settings = settings or get_settings()
        self.per_platform_timeout = per_platform_timeout

        if adapters is not None:
            self.adapters = list(adapters)
        else:
            # Instantiate all five canonical platforms with configured timeout
            self.adapters = [
                BlueskyAdapter(settings=self.settings, timeout_seconds=self.per_platform_timeout),
                MastodonAdapter(settings=self.settings, timeout_seconds=self.per_platform_timeout),
                DevtoAdapter(settings=self.settings, timeout_seconds=self.per_platform_timeout),
                WordPressAdapter(settings=self.settings, timeout_seconds=self.per_platform_timeout),
                TelegramAdapter(settings=self.settings, timeout_seconds=self.per_platform_timeout),
            ]

    async def broadcast(self, message: str) -> StandardPostingResponse:
        """Broadcast a message concurrently to all registered platforms.

        Args:
            message: Validated message string containing content and exactly one CTA URL.

        Returns:
            StandardPostingResponse: Aggregated multi-platform outcome complying with Part 7.
        """
        payload = PlatformPostPayload(content=message)

        # Prepare coroutines for all adapters
        tasks = [
            self._execute_single_platform(adapter, payload)
            for adapter in self.adapters
        ]

        # Concurrently execute all platforms with return_exceptions=True
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        normalized_results: list[StandardPlatformResult] = []
        for idx, res in enumerate(raw_results):
            if isinstance(res, StandardPlatformResult):
                normalized_results.append(res)
            elif isinstance(res, Exception):
                # Safeguard against any unexpected unhandled task exception
                adapter = self.adapters[idx]
                platform_name = PLATFORM_DISPLAY_NAMES.get(
                    adapter.platform_type,
                    adapter.platform_type.value.capitalize(),
                )
                logger.error(
                    "Unexpected task exception for platform %s: %s",
                    platform_name,
                    res,
                )
                normalized_results.append(
                    StandardPlatformResult(
                        platform=platform_name,
                        status="failed",
                        posted_url=None,
                        public_access=False,
                        date=None,
                        time=None,
                        error=f"Internal dispatch failure: {res}",
                    )
                )

        # Calculate metrics
        successful_count = sum(1 for r in normalized_results if r.status == "success")
        total_count = len(normalized_results)
        failed_count = total_count - successful_count
        overall_success = successful_count > 0

        # Construct informative aggregate message
        if overall_success and failed_count == 0:
            status_message = "Posting completed successfully across all platforms"
        elif overall_success:
            status_message = "Posting completed"
        else:
            status_message = "Posting failed across all platforms"

        return StandardPostingResponse(
            success=overall_success,
            message=status_message,
            total_platforms=total_count,
            successful=successful_count,
            failed=failed_count,
            results=normalized_results,
        )

    async def _execute_single_platform(
        self,
        adapter: BasePlatformAdapter,
        payload: PlatformPostPayload,
    ) -> StandardPlatformResult:
        """Execute a single platform adapter with per-platform timeout and isolated error trapping."""
        platform_name = PLATFORM_DISPLAY_NAMES.get(
            adapter.platform_type,
            adapter.platform_type.value.capitalize(),
        )

        try:
            # Wrap execution in per-platform timeout protection
            result = await asyncio.wait_for(
                adapter.execute_safe_publish(payload),
                timeout=self.per_platform_timeout,
            )

            if isinstance(result, PublishResult):
                # Extract actual publication timestamp from API response
                date_str, time_str = extract_platform_date_time(result.raw_response)
                # Public access is confirmed if external_url is present and verified public
                # (For Telegram private channels without username, external_url is None)
                is_public = bool(result.external_url)

                return StandardPlatformResult(
                    platform=platform_name,
                    status="success",
                    posted_url=result.external_url,
                    public_access=is_public,
                    date=date_str,
                    time=time_str,
                    error=None,
                )
            else:
                # PublishFailure (auth failed, unconfigured, validation error, etc.)
                return StandardPlatformResult(
                    platform=platform_name,
                    status="failed",
                    posted_url=None,
                    public_access=False,
                    date=None,
                    time=None,
                    error=result.error_message,
                )

        except TimeoutError:
            logger.warning(
                "Platform %s timed out after %s seconds",
                platform_name,
                self.per_platform_timeout,
            )
            return StandardPlatformResult(
                platform=platform_name,
                status="failed",
                posted_url=None,
                public_access=False,
                date=None,
                time=None,
                error=f"Operation timed out after {self.per_platform_timeout:.1f}s",
            )
        except Exception as exc:
            logger.exception(
                "Unexpected error during %s dispatch",
                platform_name,
            )
            return StandardPlatformResult(
                platform=platform_name,
                status="failed",
                posted_url=None,
                public_access=False,
                date=None,
                time=None,
                error=f"Unexpected error: {exc}",
            )
