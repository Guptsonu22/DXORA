"""Official Mastodon API (Fediverse) Adapter implementation.

Conforms to Mastodon API v1 specification:
- Status Ingestion: POST /api/v1/statuses
- OAuth 2.0 Bearer Token Authentication
- Public Status Visibility & Content Warnings (spoiler_text)
- Native Idempotency Header: Idempotency-Key
- Public Permalink Extraction (url / uri attributes)
- Account Verification & Health: GET /api/v1/accounts/verify_credentials
"""

import time
import uuid
from typing import Any

import httpx

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformNetworkError,
    PlatformRateLimitError,
    PlatformServerError,
    map_http_response_to_exception,
    parse_retry_after,
)
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PublishResult,
)
from autopost_nexus.config import Settings
from autopost_nexus.schemas.posting import PlatformType


class MastodonAdapter(BasePlatformAdapter):
    """Production-grade adapter for Mastodon instances via official REST API v1."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(settings=settings, timeout_seconds=timeout_seconds)

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.MASTODON

    @property
    def max_characters(self) -> int:
        # Standard Mastodon default limit is 500 characters
        return 500

    @property
    def auth_mode(self) -> str:
        return "OAuth 2.0 Bearer Token"

    def is_configured(self) -> bool:
        """Verify whether Mastodon access token is provided."""
        return bool(self.settings.MASTODON_ACCESS_TOKEN)

    @property
    def instance_url(self) -> str:
        """Normalized base instance URL (e.g. https://mastodon.social)."""
        return (self.settings.MASTODON_INSTANCE_URL or "https://mastodon.social").rstrip("/")

    # -----------------------------------------------------------------------
    # Publishing & Status Creation
    # -----------------------------------------------------------------------

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Publish a public status to the configured Mastodon instance.

        Sends POST /api/v1/statuses with Bearer token and native Idempotency-Key header.
        Extracts public permalink and status ID from the returned Status entity.
        """
        start = time.perf_counter()
        endpoint = f"{self.instance_url}/api/v1/statuses"

        # Generate or extract idempotency key
        idempotency_key = payload.metadata.get("idempotency_key") or str(uuid.uuid4())

        headers = {
            "Authorization": f"Bearer {self.settings.MASTODON_ACCESS_TOKEN}",
            "Idempotency-Key": idempotency_key,
        }

        # Build payload parameters
        body_params: dict[str, Any] = {
            "status": payload.content,
            "visibility": payload.metadata.get("visibility", "public"),
        }

        # Optional content warning or title mapping
        if payload.title:
            body_params["spoiler_text"] = payload.title
        elif "spoiler_text" in payload.metadata:
            body_params["spoiler_text"] = payload.metadata["spoiler_text"]

        # Optional media attachments
        if "media_ids" in payload.metadata:
            body_params["media_ids"] = payload.metadata["media_ids"]

        # Optional language code
        if "language" in payload.metadata:
            body_params["language"] = payload.metadata["language"]

        async with self.get_http_client() as client:
            try:
                response = await client.post(endpoint, json=body_params, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise PlatformNetworkError(
                    platform=self.platform_type,
                    message=f"Network drop or timeout contacting Mastodon instance at {self.instance_url}: {exc}",
                    raw_error=exc,
                ) from exc

        latency = (time.perf_counter() - start) * 1000.0

        if response.status_code == 200:
            data = response.json()
            status_id = str(data.get("id", ""))
            # Mastodon returns 'url' as the public web permalink
            permalink = (
                data.get("url") or data.get("uri") or f"{self.instance_url}/notice/{status_id}"
            )

            return PublishResult(
                success=True,
                platform=self.platform_type,
                external_post_id=status_id,
                external_url=permalink,
                latency_ms=round(latency, 2),
                raw_response=data,
            )

        # Handle Mastodon-specific error statuses
        if response.status_code in (401, 403):
            err_msg = self._extract_error_message(
                response, "Invalid or revoked Mastodon access token"
            )
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message=f"Mastodon authentication failed (HTTP {response.status_code}): {err_msg}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code == 422:
            err_msg = self._extract_error_message(response, "Status validation failed")
            raise PlatformContentValidationError(
                platform=self.platform_type,
                message=f"Mastodon rejected status content (HTTP 422): {err_msg}",
                status_code=422,
                response_body=response.text,
            )

        if response.status_code == 429:
            retry_after = self._parse_mastodon_rate_limit(response)
            raise PlatformRateLimitError(
                platform=self.platform_type,
                message="Mastodon rate limit exceeded",
                retry_after_seconds=retry_after,
            )

        if response.status_code >= 500:
            raise PlatformServerError(
                platform=self.platform_type,
                message=f"Mastodon instance error at {self.instance_url} (HTTP {response.status_code})",
                status_code=response.status_code,
                response_body=response.text,
            )

        raise map_http_response_to_exception(self.platform_type, response)

    # -----------------------------------------------------------------------
    # Health Diagnostics & Account Verification
    # -----------------------------------------------------------------------

    async def check_health(self) -> PlatformHealthResult:
        """Verify token validity and instance reachability via verify_credentials."""
        start = time.perf_counter()
        if not self.is_configured():
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=False,
                auth_mode=self.auth_mode,
                latency_ms=None,
                details="Mastodon access token is not configured in environment.",
            )

        endpoint = f"{self.instance_url}/api/v1/accounts/verify_credentials"
        headers = {"Authorization": f"Bearer {self.settings.MASTODON_ACCESS_TOKEN}"}

        async with self.get_http_client() as client:
            try:
                response = await client.get(endpoint, headers=headers)
                latency = (time.perf_counter() - start) * 1000.0
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                latency = (time.perf_counter() - start) * 1000.0
                return PlatformHealthResult(
                    platform=self.platform_type,
                    is_healthy=False,
                    is_configured=True,
                    auth_mode=self.auth_mode,
                    latency_ms=round(latency, 2),
                    details=f"Network connectivity error to {self.instance_url}: {exc}",
                )

        if response.status_code == 200:
            account = response.json()
            username = account.get("username", "unknown")
            acct = account.get("acct", username)
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=True,
                is_configured=True,
                auth_mode=self.auth_mode,
                latency_ms=round(latency, 2),
                details=f"Connected as @{acct} on {self.instance_url}",
            )

        err_msg = self._extract_error_message(response, "Credentials verification failed")
        return PlatformHealthResult(
            platform=self.platform_type,
            is_healthy=False,
            is_configured=True,
            auth_mode=self.auth_mode,
            latency_ms=round(latency, 2),
            details=f"Verification failed (HTTP {response.status_code}): {err_msg}",
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_error_message(response: httpx.Response, fallback: str) -> str:
        """Extract human-readable error from Mastodon JSON response (e.g. {'error': '...'})."""
        try:
            data = response.json()
            if isinstance(data, dict):
                return data.get("error") or data.get("error_description") or fallback
        except (ValueError, KeyError, httpx.HTTPError):
            pass
        return fallback

    @staticmethod
    def _parse_mastodon_rate_limit(response: httpx.Response) -> float:
        """Parse Retry-After or X-RateLimit-Reset headers for cooldown duration.

        Per the official Mastodon API docs (docs.joinmastodon.org/api/rate-limits):
        - Standard `Retry-After` header: integer seconds to wait.
        - `X-RateLimit-Reset`: ISO 8601 datetime string when the window resets.
          Example: "2019-12-02T12:00:00.000Z"
        """
        # 1. Standard Retry-After header (highest precedence)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            return parse_retry_after(retry_after)

        # 2. Mastodon-native X-RateLimit-Reset (ISO 8601 datetime per official docs)
        reset_header = response.headers.get("X-RateLimit-Reset")
        if reset_header:
            # Try ISO 8601 datetime first (official Mastodon format)
            try:
                from datetime import UTC, datetime

                reset_dt = datetime.fromisoformat(reset_header)
                now_dt = datetime.now(UTC)
                delta = (reset_dt - now_dt).total_seconds()
                return max(round(delta, 1), 1.0)
            except (ValueError, TypeError):
                pass
            # Fallback: Unix timestamp (some older Mastodon forks)
            try:
                reset_ts = float(reset_header)
                now_ts = time.time()
                delta = reset_ts - now_ts
                return max(round(delta, 1), 1.0)
            except ValueError:
                pass

        return 60.0
