"""Official WordPress REST API Adapter implementation.

Conforms to WordPress REST API v2 specification (WP 5.6+ Application Passwords):
- Posts Ingestion: POST /wp-json/wp/v2/posts
- Authentication: HTTP Basic Auth with WordPress Application Passwords
- Title Generation: Extracts meaningful title from broadcast message or preserves explicit title
- Published State: Sets `status="publish"` and verifies published outcome
- Permalink Extraction: Extracts canonical `link` attribute from post entity
- Health & Diagnostics: GET /wp-json/wp/v2/users/me
- Inaccessible Sites & Credential Error Handling
"""

import base64
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

URL_REGEX = re.compile(r"https?://[^\s<>\"']+")


class WordPressAdapter(BasePlatformAdapter):
    """Production-grade adapter for WordPress sites via official REST API v2."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(settings=settings, timeout_seconds=timeout_seconds)

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.WORDPRESS

    @property
    def max_characters(self) -> int:
        # WordPress post body capacity
        return 65536

    @property
    def auth_mode(self) -> str:
        return "HTTP Basic (Application Password)"

    def is_configured(self) -> bool:
        """Verify whether WordPress site URL, username, and Application Password are provided."""
        return bool(
            self.settings.WORDPRESS_SITE_URL
            and self.settings.WORDPRESS_USERNAME
            and self.settings.WORDPRESS_APP_PASSWORD
        )

    @property
    def site_url(self) -> str:
        """Normalized base WordPress site URL (e.g. https://example.com)."""
        raw = (self.settings.WORDPRESS_SITE_URL or "").strip().rstrip("/")
        # If user configured path with wp-json/wp/v2, strip back to root domain/path
        raw = re.sub(r"/wp-json(/wp/v2)?/?$", "", raw)
        return raw

    @property
    def api_base(self) -> str:
        """Absolute URL to the WordPress REST API v2 namespace."""
        return f"{self.site_url}/wp-json/wp/v2"

    # -----------------------------------------------------------------------
    # Authentication Header Helpers
    # -----------------------------------------------------------------------

    def get_auth_header(self) -> dict[str, str]:
        """Construct HTTP Basic Authentication header using Application Password.

        Application Passwords in WordPress are generated as spaced 4-character chunks
        (e.g. 'abcd efgh ijkl mnop'). Both spaced and unspaced variants work with
        HTTP Basic Auth when base64-encoded.
        """
        username = self.settings.WORDPRESS_USERNAME or ""
        app_password = self.settings.WORDPRESS_APP_PASSWORD or ""
        token = base64.b64encode(f"{username}:{app_password}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    # -----------------------------------------------------------------------
    # Content Formatting Helpers
    # -----------------------------------------------------------------------

    def format_post(self, payload: PlatformPostPayload) -> tuple[str, str]:
        """Transform a broadcast message into a WordPress post title and HTML content.

        Returns:
            tuple: (title, content_html)
        """
        raw_content = payload.content.strip()

        # 1. Determine Title
        if payload.title and payload.title.strip():
            title = payload.title.strip()
        else:
            # Strip URLs and extract the first sentence/clause
            clean_text = URL_REGEX.sub("", raw_content).strip()
            clean_text = re.sub(r"\s+", " ", clean_text)

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

        # 2. Format Body Content
        custom_content = payload.metadata.get("content_html") or payload.metadata.get("body")
        if custom_content and str(custom_content).strip():
            content = str(custom_content).strip()
        else:
            # Clean HTML paragraph representation of content
            content = f"<p>{raw_content}</p>"

        return title, content

    # -----------------------------------------------------------------------
    # Publishing & Post Creation
    # -----------------------------------------------------------------------

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Publish a post to WordPress via POST /wp-json/wp/v2/posts.

        Guarantees:
        - Authenticates with WordPress Application Password via HTTP Basic Auth.
        - Generates meaningful title from submitted message.
        - Sets `status="publish"` to ensure immediate publication.
        - Validates that returned post has `status="publish"`.
        - Extracts the public `link` permalink from the post entity.
        - Catches invalid credentials and inaccessible host errors.
        """
        start = time.perf_counter()
        endpoint = f"{self.api_base}/posts"

        title, content = self.format_post(payload)

        post_body: dict[str, Any] = {
            "title": title,
            "content": content,
            "status": "publish",  # Enforce published status per master prompt
        }

        # Optional metadata forwarding
        if "slug" in payload.metadata:
            post_body["slug"] = payload.metadata["slug"]
        if "categories" in payload.metadata:
            post_body["categories"] = payload.metadata["categories"]
        if "tags" in payload.metadata:
            post_body["tags"] = payload.metadata["tags"]
        if "excerpt" in payload.metadata:
            post_body["excerpt"] = payload.metadata["excerpt"]

        headers = {
            **self.get_auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with self.get_http_client() as client:
            try:
                response = await client.post(endpoint, json=post_body, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise PlatformNetworkError(
                    platform=self.platform_type,
                    message=f"Inaccessible WordPress site at {self.site_url}: {exc}",
                    raw_error=exc,
                ) from exc

        latency = (time.perf_counter() - start) * 1000.0

        if response.status_code == 201:
            data = response.json()

            # Verify that the post is genuinely published
            status = data.get("status")
            if status != "publish":
                raise PlatformContentValidationError(
                    platform=self.platform_type,
                    message=(
                        f"WordPress post was created with status '{status}' instead of 'publish'. "
                        "Publication cannot be considered successful."
                    ),
                    status_code=422,
                    response_body=response.text,
                )

            post_id = str(data.get("id", ""))
            # Extract actual public permalink
            permalink = data.get("link") or data.get("guid", {}).get("rendered") or f"{self.site_url}/?p={post_id}"

            return PublishResult(
                success=True,
                platform=self.platform_type,
                external_post_id=post_id,
                external_url=permalink,
                latency_ms=round(latency, 2),
                raw_response={
                    "id": data.get("id"),
                    "status": data.get("status"),
                    "link": data.get("link"),
                    "title": data.get("title", {}).get("rendered"),
                },
            )

        # Handle WordPress REST API error responses
        if response.status_code in (401, 403):
            err_msg = self._extract_error_message(response, "Invalid username or Application Password")
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message=f"WordPress authentication failed (HTTP {response.status_code}): {err_msg}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code in (400, 422):
            err_msg = self._extract_error_message(response, "Invalid post payload or content validation failed")
            raise PlatformContentValidationError(
                platform=self.platform_type,
                message=f"WordPress rejected post payload (HTTP {response.status_code}): {err_msg}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            raise PlatformRateLimitError(
                platform=self.platform_type,
                message=f"WordPress rate limit exceeded (HTTP 429). Retry after {retry_after}s",
                status_code=429,
                retry_after_seconds=retry_after,
            )

        if response.status_code >= 500:
            raise PlatformServerError(
                platform=self.platform_type,
                message=f"WordPress server error at {self.site_url} (HTTP {response.status_code})",
                status_code=response.status_code,
                response_body=response.text,
            )

        raise map_http_response_to_exception(self.platform_type, response)

    # -----------------------------------------------------------------------
    # Health Diagnostics
    # -----------------------------------------------------------------------

    async def check_health(self) -> PlatformHealthResult:
        """Verify Application Password validity and WordPress site accessibility via GET /wp-json/wp/v2/users/me."""
        start = time.perf_counter()
        if not self.is_configured():
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=False,
                auth_mode=self.auth_mode,
                latency_ms=None,
                details="WordPress site URL, username, or application password not configured in environment.",
            )

        endpoint = f"{self.api_base}/users/me"
        headers = {
            **self.get_auth_header(),
            "Accept": "application/json",
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
                    details=f"Inaccessible WordPress site at {self.site_url}: {exc}",
                )

        if response.status_code == 200:
            user = response.json()
            username = user.get("slug") or user.get("name") or self.settings.WORDPRESS_USERNAME
            name = user.get("name", username)
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=True,
                is_configured=True,
                auth_mode=self.auth_mode,
                latency_ms=round(latency, 2),
                details=f"Authenticated as '{name}' (@{username}) on {self.site_url}",
            )

        err_msg = self._extract_error_message(response, "Application Password verification failed")
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
        """Extract human-readable error from WordPress REST API error response."""
        try:
            data = response.json()
            if isinstance(data, dict):
                msg = data.get("message")
                code = data.get("code")
                if msg and code and code.lower() not in msg.lower():
                    return f"{code}: {msg}"
                return msg or code or fallback
        except (ValueError, KeyError, httpx.HTTPError):
            pass
        return fallback
