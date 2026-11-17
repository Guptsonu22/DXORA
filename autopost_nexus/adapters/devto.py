"""Official DEV.to (Forem API v1) Adapter implementation.

Conforms to Forem API v1 specification:
- Article Ingestion: POST /api/articles
- Authentication: API Key via `api-key` header
- Content Formatting: Converts short broadcast messages into rich article title,
  Markdown body, and canonical URL
- Publishing Verification: Requires `published=True` and verifies returned status
  is genuinely published (rejects drafts)
- Canonical URL Extraction: Extracts `canonical_url` and web `url` from response
- Diagnostics & Health: GET /api/users/me
"""

import re
import time
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

# URL regex for extracting CTA link
URL_REGEX = re.compile(r"https?://[^\s<>\"']+")
HASHTAG_REGEX = re.compile(r"(?:^|\s)#([A-Za-z0-9_]+)")


class DevtoAdapter(BasePlatformAdapter):
    """Production-grade adapter for DEV.to via official Forem REST API v1."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(settings=settings, timeout_seconds=timeout_seconds)

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.DEVTO

    @property
    def max_characters(self) -> int:
        # DEV.to markdown body capacity
        return 65536

    @property
    def auth_mode(self) -> str:
        return "API Key Header (api-key)"

    def is_configured(self) -> bool:
        """Verify whether DEV.to API key is provided."""
        return bool(self.settings.DEVTO_API_KEY)

    @property
    def base_url(self) -> str:
        """Normalized base URL for DEV.to (e.g. https://dev.to)."""
        return (getattr(self.settings, "DEVTO_BASE_URL", None) or "https://dev.to").rstrip("/")

    # -----------------------------------------------------------------------
    # Content Formatting Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def extract_cta_url(text: str) -> str | None:
        """Extract the first CTA URL from message text if present."""
        match = URL_REGEX.search(text)
        if match:
            return match.group(0).rstrip(".,;:!?)")
        return None

    @staticmethod
    def extract_hashtags(text: str) -> list[str]:
        """Extract hashtags and normalize to lowercase alphanumeric tags."""
        tags = []
        for match in HASHTAG_REGEX.finditer(text):
            tag = re.sub(r"[^a-z0-9]", "", match.group(1).lower())
            if tag and tag not in tags:
                tags.append(tag)
        return tags[:4]

    def format_article(
        self,
        payload: PlatformPostPayload,
    ) -> tuple[str, str, str | None, list[str]]:
        """Transform a short broadcast message into a structured DEV.to article.

        Returns:
            tuple: (title, body_markdown, canonical_url, tags)
        """
        raw_content = payload.content.strip()

        # 1. Determine Title
        if payload.title and payload.title.strip():
            title = payload.title.strip()
        else:
            # Generate a meaningful title from text without URL
            clean_text = URL_REGEX.sub("", raw_content).strip()
            # Clean extra whitespaces or punctuation
            clean_text = re.sub(r"\s+", " ", clean_text)

            # Look for the first sentence or clause
            sentence_match = re.split(r"[.!?\n]", clean_text)
            first_clause = sentence_match[0].strip() if sentence_match else ""

            if len(first_clause) >= 5:
                title = first_clause
            elif len(clean_text) >= 5:
                title = clean_text[:100]
            else:
                title = "Announcement: New Platform Update"

            # Enforce max title length of 120 chars
            if len(title) > 120:
                title = title[:117].rstrip() + "..."

        # 2. Extract Canonical URL
        canonical_url = payload.metadata.get("canonical_url") or self.extract_cta_url(raw_content)

        # 3. Format Body Markdown
        custom_body = payload.metadata.get("body_markdown")
        if custom_body and custom_body.strip():
            body_markdown = custom_body.strip()
        else:
            # Build clean Markdown body from message
            body_markdown = raw_content

        # 4. Extract Tags (up to 4)
        custom_tags = payload.metadata.get("tags")
        if isinstance(custom_tags, list) and custom_tags:
            tags = [
                re.sub(r"[^a-z0-9]", "", str(t).lower())
                for t in custom_tags
                if str(t).strip()
            ][:4]
        else:
            tags = self.extract_hashtags(raw_content)

        return title, body_markdown, canonical_url, tags

    # -----------------------------------------------------------------------
    # Publishing & Article Creation
    # -----------------------------------------------------------------------

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Publish an article to DEV.to via POST /api/articles.

        Guarantees:
        - `published=True` is explicitly passed.
        - Verifies that the returned article has `published=True`.
        - Rejects drafts with `PlatformContentValidationError`.
        - Extracts the canonical article URL.
        """
        start = time.perf_counter()
        endpoint = f"{self.base_url}/api/articles"

        title, body_markdown, canonical_url, tags = self.format_article(payload)

        # Construct Forem v1 payload
        article_data: dict[str, Any] = {
            "title": title,
            "body_markdown": body_markdown,
            "published": True,  # Mandatory: genuine publication, never draft
        }

        if canonical_url:
            article_data["canonical_url"] = canonical_url

        if tags:
            article_data["tags"] = tags

        if payload.metadata.get("series"):
            article_data["series"] = payload.metadata["series"]

        if payload.metadata.get("main_image"):
            article_data["main_image"] = payload.metadata["main_image"]

        if payload.metadata.get("description"):
            article_data["description"] = payload.metadata["description"]

        headers = {
            "api-key": self.settings.DEVTO_API_KEY,
            "Accept": "application/vnd.forem.api-v1+json",
            "Content-Type": "application/json",
        }

        async with self.get_http_client() as client:
            try:
                response = await client.post(
                    endpoint,
                    json={"article": article_data},
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise PlatformNetworkError(
                    platform=self.platform_type,
                    message=f"Network drop or timeout contacting DEV.to API at {self.base_url}: {exc}",
                    raw_error=exc,
                ) from exc

        latency = (time.perf_counter() - start) * 1000.0

        if response.status_code == 201:
            data = response.json()

            # CRITICAL VERIFICATION: Ensure the content is genuinely published.
            # Do not claim that a draft is a successful publication.
            is_published = data.get("published", False)
            if not is_published:
                raise PlatformContentValidationError(
                    platform=self.platform_type,
                    message=(
                        "DEV.to article was saved as a draft (published=false) instead of being published. "
                        "Publication cannot be considered successful."
                    ),
                    status_code=422,
                    response_body=response.text,
                )

            article_id = str(data.get("id", ""))
            # Extract canonical URL: response canonical_url or public live URL
            canonical_article_url = data.get("canonical_url") or data.get("url")

            return PublishResult(
                success=True,
                platform=self.platform_type,
                external_post_id=article_id,
                external_url=canonical_article_url,
                latency_ms=round(latency, 2),
                raw_response={
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "published": data.get("published"),
                    "url": data.get("url"),
                    "canonical_url": data.get("canonical_url"),
                },
            )

        # Handle DEV.to error status codes
        if response.status_code in (401, 403):
            err_msg = self._extract_error_message(response, "Invalid or unauthorized DEV.to API key")
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message=f"DEV.to authentication failed (HTTP {response.status_code}): {err_msg}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code == 422:
            err_msg = self._extract_error_message(response, "Article validation failed")
            raise PlatformContentValidationError(
                platform=self.platform_type,
                message=f"DEV.to rejected article payload (HTTP 422): {err_msg}",
                status_code=422,
                response_body=response.text,
            )

        if response.status_code == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            raise PlatformRateLimitError(
                platform=self.platform_type,
                message=f"DEV.to rate limit exceeded (HTTP 429). Retry after {retry_after}s",
                status_code=429,
                retry_after_seconds=retry_after,
            )

        if response.status_code >= 500:
            raise PlatformServerError(
                platform=self.platform_type,
                message=f"DEV.to server error at {self.base_url} (HTTP {response.status_code})",
                status_code=response.status_code,
                response_body=response.text,
            )

        raise map_http_response_to_exception(self.platform_type, response)

    # -----------------------------------------------------------------------
    # Health Diagnostics
    # -----------------------------------------------------------------------

    async def check_health(self) -> PlatformHealthResult:
        """Verify API key validity and DEV.to reachability via GET /api/users/me."""
        start = time.perf_counter()
        if not self.is_configured():
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=False,
                auth_mode=self.auth_mode,
                latency_ms=None,
                details="DEV.to API key is not configured in environment.",
            )

        endpoint = f"{self.base_url}/api/users/me"
        headers = {
            "api-key": self.settings.DEVTO_API_KEY,
            "Accept": "application/vnd.forem.api-v1+json",
        }

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
                    details=f"Network connectivity error to {self.base_url}: {exc}",
                )

        if response.status_code == 200:
            user = response.json()
            username = user.get("username", "unknown")
            name = user.get("name", username)
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=True,
                is_configured=True,
                auth_mode=self.auth_mode,
                latency_ms=round(latency, 2),
                details=f"Authenticated as @{username} ({name}) on {self.base_url}",
            )

        err_msg = self._extract_error_message(response, "API key verification failed")
        return PlatformHealthResult(
            platform=self.platform_type,
            is_healthy=False,
            is_configured=True,
            auth_mode=self.auth_mode,
            latency_ms=round(latency, 2),
            details=f"Verification failed (HTTP {response.status_code}): {err_msg}",
        )

    # -----------------------------------------------------------------------
    # Helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_error_message(response: httpx.Response, fallback: str) -> str:
        """Extract human-readable error explanation from DEV.to JSON response."""
        try:
            data = response.json()
            if isinstance(data, dict):
                msg = data.get("message")
                err = data.get("error")
                errs = data.get("errors")
                if msg and err and msg.lower() != err.lower():
                    return f"{err}: {msg}"
                return msg or err or (str(errs) if errs else fallback)
        except (ValueError, KeyError, httpx.HTTPError):
            pass
        return fallback
