"""Official Bluesky (AT Protocol) Adapter implementation.

Interacts directly with the AT Protocol XRPC API specification:
- Session Creation: com.atproto.server.createSession
- Record Ingestion: com.atproto.repo.createRecord (app.bsky.feed.post)
- Rich Text Faceting: URL detection with strict UTF-8 byte offset indices
- Public Web URL Construction: https://bsky.app/profile/{handle}/post/{rkey}
"""

import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.exceptions import (
    PlatformAuthenticationError,
    PlatformContentValidationError,
    PlatformError,
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

# Standard URL regex according to AT Protocol rich text conventions
URL_REGEX = re.compile(r"https?://[^\s<>\"']+")
HASHTAG_REGEX = re.compile(r"(?:^|\s)#([A-Za-z0-9_]+)")


class BlueskyAdapter(BasePlatformAdapter):
    """Production-grade adapter for Bluesky via AT Protocol XRPC endpoints."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(settings=settings, timeout_seconds=timeout_seconds)
        self._cached_session: dict[str, Any] | None = None

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.BLUESKY

    @property
    def max_characters(self) -> int:
        # AT Protocol allows 300 graphemes per post
        return 300

    @property
    def auth_mode(self) -> str:
        return "AT Protocol XRPC (App Password)"

    def is_configured(self) -> bool:
        """Verify whether Bluesky handle and app password are configured."""
        return bool(self.settings.BLUESKY_HANDLE and self.settings.BLUESKY_APP_PASSWORD)

    @property
    def service_url(self) -> str:
        """Base service URL (default: https://bsky.social)."""
        return (self.settings.BLUESKY_SERVICE_URL or "https://bsky.social").rstrip("/")

    # -----------------------------------------------------------------------
    # Rich Text Facet Extraction (Exact UTF-8 Byte Offset Standard)
    # -----------------------------------------------------------------------

    @staticmethod
    def extract_facets(text: str) -> list[dict[str, Any]]:
        """Extract URLs and hashtags into AT Protocol Richtext Facets.

        AT Protocol mandates byte-start and byte-end indices based on UTF-8 encoding,
        ensuring cross-language accuracy with multi-byte unicode characters and emojis.
        """
        facets: list[dict[str, Any]] = []

        # 1. Extract URLs
        for match in URL_REGEX.finditer(text):
            raw_url = match.group(0)
            # Trim trailing punctuation often attached to URLs in prose
            clean_url = raw_url.rstrip(".,;:!?)")
            if not clean_url:
                continue

            # Calculate exact byte range in UTF-8
            char_start = match.start()
            char_end = char_start + len(clean_url)
            byte_start = len(text[:char_start].encode("utf-8"))
            byte_end = len(text[:char_end].encode("utf-8"))

            facets.append(
                {
                    "$type": "app.bsky.richtext.facet",
                    "index": {
                        "byteStart": byte_start,
                        "byteEnd": byte_end,
                    },
                    "features": [
                        {
                            "$type": "app.bsky.richtext.facet#link",
                            "uri": clean_url,
                        }
                    ],
                }
            )

        # 2. Extract Hashtags
        for match in HASHTAG_REGEX.finditer(text):
            tag = match.group(1)
            # Find exact position of '#'
            tag_start_in_match = match.group(0).find(f"#{tag}")
            char_start = match.start() + tag_start_in_match
            char_end = char_start + len(tag) + 1  # include '#'

            byte_start = len(text[:char_start].encode("utf-8"))
            byte_end = len(text[:char_end].encode("utf-8"))

            facets.append(
                {
                    "$type": "app.bsky.richtext.facet",
                    "index": {
                        "byteStart": byte_start,
                        "byteEnd": byte_end,
                    },
                    "features": [
                        {
                            "$type": "app.bsky.richtext.facet#tag",
                            "tag": tag,
                        }
                    ],
                }
            )

        # Sort facets by byteStart as required by AT Protocol Lexicon
        facets.sort(key=lambda f: f["index"]["byteStart"])
        return facets

    # -----------------------------------------------------------------------
    # Authentication & Session Management
    # -----------------------------------------------------------------------

    async def create_session(self, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        """Authenticate via com.atproto.server.createSession and obtain accessJwt.

        Returns:
            dict containing: { "accessJwt": ..., "did": ..., "handle": ... }
        Raises:
            PlatformAuthenticationError, PlatformRateLimitError, or PlatformNetworkError.
        """
        endpoint = f"{self.service_url}/xrpc/com.atproto.server.createSession"
        payload = {
            "identifier": self.settings.BLUESKY_HANDLE,
            "password": self.settings.BLUESKY_APP_PASSWORD,
        }

        should_close = False
        if client is None:
            client = self.get_http_client()
            should_close = True

        try:
            response = await client.post(endpoint, json=payload)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise PlatformNetworkError(
                platform=self.platform_type,
                message=f"Timeout or network drop during Bluesky authentication: {exc}",
                raw_error=exc,
            ) from exc
        finally:
            if should_close:
                await client.aclose()

        if response.status_code == 200:
            session_data = response.json()
            self._cached_session = session_data
            return session_data

        if response.status_code in (401, 403):
            err_msg = self._extract_error_message(
                response, "Invalid Bluesky handle or app password"
            )
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message=err_msg,
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            raise PlatformRateLimitError(
                platform=self.platform_type,
                message="Bluesky auth rate limit exceeded",
                retry_after_seconds=retry_after,
            )

        raise map_http_response_to_exception(self.platform_type, response)

    async def get_valid_session(
        self,
        client: httpx.AsyncClient,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return active cached session or create a new one."""
        if not force_refresh and self._cached_session and "accessJwt" in self._cached_session:
            return self._cached_session
        return await self.create_session(client)

    # -----------------------------------------------------------------------
    # Publishing & Record Creation
    # -----------------------------------------------------------------------

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Publish post to Bluesky using com.atproto.repo.createRecord."""
        start = time.perf_counter()
        async with self.get_http_client() as client:
            session = await self.get_valid_session(client)

            # Build app.bsky.feed.post record
            facets = self.extract_facets(payload.content)
            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            record: dict[str, Any] = {
                "$type": "app.bsky.feed.post",
                "text": payload.content,
                "createdAt": now_iso,
            }
            if facets:
                record["facets"] = facets

            create_record_url = f"{self.service_url}/xrpc/com.atproto.repo.createRecord"
            request_body = {
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": record,
            }
            headers = {"Authorization": f"Bearer {session['accessJwt']}"}

            try:
                response = await client.post(create_record_url, json=request_body, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise PlatformNetworkError(
                    platform=self.platform_type,
                    message=f"Network drop while publishing to Bluesky: {exc}",
                    raw_error=exc,
                ) from exc

            # If token expired or rejected, refresh session once and retry
            if response.status_code == 401:
                self._cached_session = None
                session = await self.create_session(client)
                headers = {"Authorization": f"Bearer {session['accessJwt']}"}
                request_body["repo"] = session["did"]
                response = await client.post(create_record_url, json=request_body, headers=headers)

            latency = (time.perf_counter() - start) * 1000.0

            if response.status_code == 200:
                data = response.json()
                at_uri: str = data.get("uri", "")
                rkey = at_uri.split("/")[-1] if "/" in at_uri else at_uri
                user_handle = session.get("handle") or session.get("did")
                public_url = f"https://bsky.app/profile/{user_handle}/post/{rkey}"

                return PublishResult(
                    success=True,
                    platform=self.platform_type,
                    external_post_id=at_uri,
                    external_url=public_url,
                    latency_ms=round(latency, 2),
                    raw_response=data,
                )

            # Handle AT Protocol specific errors
            if response.status_code == 400:
                err_msg = self._extract_error_message(response, "Invalid post record payload")
                raise PlatformContentValidationError(
                    platform=self.platform_type,
                    message=f"Bluesky rejected post record: {err_msg}",
                    response_body=response.text,
                )

            if response.status_code == 429:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                raise PlatformRateLimitError(
                    platform=self.platform_type,
                    message="Bluesky posting rate limit exceeded",
                    retry_after_seconds=retry_after,
                )

            if response.status_code >= 500:
                raise PlatformServerError(
                    platform=self.platform_type,
                    message=f"Bluesky XRPC service error (HTTP {response.status_code})",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            raise map_http_response_to_exception(self.platform_type, response)

    # -----------------------------------------------------------------------
    # Health Diagnostics
    # -----------------------------------------------------------------------

    async def check_health(self) -> PlatformHealthResult:
        """Verify Bluesky connection and credentials."""
        start = time.perf_counter()
        if not self.is_configured():
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=False,
                auth_mode=self.auth_mode,
                latency_ms=None,
                details="Bluesky handle or app password missing in environment.",
            )

        try:
            session = await self.create_session()
            latency = (time.perf_counter() - start) * 1000.0
            handle = session.get("handle", self.settings.BLUESKY_HANDLE)
            did = session.get("did", "unknown")
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=True,
                is_configured=True,
                auth_mode=self.auth_mode,
                latency_ms=round(latency, 2),
                details=f"Authenticated as @{handle} ({did}) on {self.service_url}",
            )
        except PlatformError as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=True,
                auth_mode=self.auth_mode,
                latency_ms=round(latency, 2),
                details=f"Authentication failed: {exc.message}",
            )

    @staticmethod
    def _extract_error_message(response: httpx.Response, fallback: str) -> str:
        """Parse AT Protocol error JSON body (e.g. {'error': '...', 'message': '...'}):"""
        try:
            data = response.json()
            if isinstance(data, dict):
                return data.get("message") or data.get("error") or fallback
        except (ValueError, KeyError, httpx.HTTPError):
            pass
        return fallback
