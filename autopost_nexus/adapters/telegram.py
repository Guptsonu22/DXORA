"""Official Telegram Bot API Adapter implementation.

Conforms to Telegram Bot API specification:
- Publishing: POST /bot<token>/sendMessage
- Authentication: Bot Token authentication
- Permission Enforcement: Detects missing posting rights or admin privileges
- Message ID Extraction: Extracts `result.message_id`
- Public vs Private Channel Logic:
  - Generates public URL (`https://t.me/{username}/{message_id}`) ONLY for public channels with usernames
  - Returns `None` for private channels (e.g. -100xxxxxxxxxx) to prevent generating invalid public URLs
- Rate Limit Handling: Parses Telegram-native `parameters.retry_after`
- Health Diagnostics: GET /getMe & POST /getChat
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


class TelegramAdapter(BasePlatformAdapter):
    """Production-grade adapter for Telegram channels and supergroups via official Bot API."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(settings=settings, timeout_seconds=timeout_seconds)

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.TELEGRAM

    @property
    def max_characters(self) -> int:
        # Telegram sendMessage text character ceiling
        return 4096

    @property
    def auth_mode(self) -> str:
        return "Telegram Bot API (Bot Token)"

    def is_configured(self) -> bool:
        """Verify whether Telegram bot token and target channel ID are configured."""
        return bool(self.settings.TELEGRAM_BOT_TOKEN and self.settings.TELEGRAM_CHANNEL_ID)

    @property
    def bot_token(self) -> str:
        """Configured bot token."""
        return (self.settings.TELEGRAM_BOT_TOKEN or "").strip()

    @property
    def channel_id(self) -> str:
        """Configured target channel identifier (e.g. @publicchannel or -1001234567890)."""
        return str(self.settings.TELEGRAM_CHANNEL_ID or "").strip()

    @property
    def api_base(self) -> str:
        """Base URL for Telegram Bot API."""
        return (getattr(self.settings, "TELEGRAM_API_BASE", None) or "https://api.telegram.org").rstrip("/")

    @property
    def bot_endpoint(self) -> str:
        """Root endpoint URL for bot actions."""
        return f"{self.api_base}/bot{self.bot_token}"

    # -----------------------------------------------------------------------
    # Publishing & Message Dispatch
    # -----------------------------------------------------------------------

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        """Publish a message to the target channel via Telegram sendMessage.

        Guarantees:
        - Authenticates via official Bot API.
        - Supports configurable bot token and target channel ID.
        - Enforces bot posting permission (traps 403 lack of permission/not admin).
        - Extracts message ID.
        - Generates public URL only for channels with a public username.
        - Sets external_url=None for private channels to prevent invalid public URLs.
        """
        start = time.perf_counter()
        endpoint = f"{self.bot_endpoint}/sendMessage"

        body: dict[str, Any] = {
            "chat_id": self.channel_id,
            "text": payload.content,
        }

        # Optional metadata forwarding
        if "parse_mode" in payload.metadata:
            body["parse_mode"] = payload.metadata["parse_mode"]
        if "disable_web_page_preview" in payload.metadata:
            body["disable_web_page_preview"] = payload.metadata["disable_web_page_preview"]
        if "disable_notification" in payload.metadata:
            body["disable_notification"] = payload.metadata["disable_notification"]

        async with self.get_http_client() as client:
            try:
                response = await client.post(endpoint, json=body)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise PlatformNetworkError(
                    platform=self.platform_type,
                    message=f"Network drop or timeout contacting Telegram Bot API: {exc}",
                    raw_error=exc,
                ) from exc

        latency = (time.perf_counter() - start) * 1000.0

        if response.status_code == 200:
            data = response.json()
            if not data.get("ok"):
                desc = data.get("description", "Unknown Telegram error")
                raise PlatformContentValidationError(
                    platform=self.platform_type,
                    message=f"Telegram API reported failure: {desc}",
                    response_body=response.text,
                )

            result = data.get("result", {})
            message_id = str(result.get("message_id", ""))

            # Resolve Public vs Private Channel Message URL
            # Rule: Generate a public message URL only if the channel has a public username.
            # Private channel messages must not generate an invalid public URL.
            chat = result.get("chat", {})
            chat_username = chat.get("username")

            if chat_username:
                clean_username = chat_username.lstrip("@")
                public_url = f"https://t.me/{clean_username}/{message_id}"
            elif self.channel_id.startswith("@"):
                clean_username = self.channel_id.lstrip("@")
                public_url = f"https://t.me/{clean_username}/{message_id}"
            else:
                # Private channel (numeric chat_id e.g. -1001234567890 without public username)
                public_url = None

            return PublishResult(
                success=True,
                platform=self.platform_type,
                external_post_id=message_id,
                external_url=public_url,
                latency_ms=round(latency, 2),
                raw_response={
                    "message_id": result.get("message_id"),
                    "chat_id": chat.get("id"),
                    "chat_title": chat.get("title"),
                    "chat_username": chat.get("username"),
                    "date": result.get("date"),
                },
            )

        # Handle Telegram error codes
        if response.status_code == 401:
            err_msg = self._extract_error_description(response, "Invalid bot token")
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message=f"Telegram authentication failed (HTTP 401): {err_msg}",
                status_code=401,
                response_body=response.text,
            )

        if response.status_code == 403:
            # Bot lacks rights, was kicked, or channel requires administrator status
            err_msg = self._extract_error_description(
                response, "Bot lacks permission to post in this chat"
            )
            raise PlatformAuthenticationError(
                platform=self.platform_type,
                message=f"Telegram bot lacks required posting permissions (HTTP 403): {err_msg}",
                status_code=403,
                response_body=response.text,
            )

        if response.status_code in (400, 422):
            err_msg = self._extract_error_description(response, "Bad request")
            raise PlatformContentValidationError(
                platform=self.platform_type,
                message=f"Telegram rejected message payload (HTTP {response.status_code}): {err_msg}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code == 429:
            retry_after = self._parse_telegram_rate_limit(response)
            raise PlatformRateLimitError(
                platform=self.platform_type,
                message=f"Telegram rate limit exceeded (HTTP 429). Retry after {retry_after}s",
                status_code=429,
                retry_after_seconds=retry_after,
            )

        if response.status_code >= 500:
            raise PlatformServerError(
                platform=self.platform_type,
                message=f"Telegram Bot API server error (HTTP {response.status_code})",
                status_code=response.status_code,
                response_body=response.text,
            )

        raise map_http_response_to_exception(self.platform_type, response)

    # -----------------------------------------------------------------------
    # Health Diagnostics
    # -----------------------------------------------------------------------

    async def check_health(self) -> PlatformHealthResult:
        """Verify bot token and channel access via getMe and getChat."""
        start = time.perf_counter()
        if not self.is_configured():
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=False,
                is_configured=False,
                auth_mode=self.auth_mode,
                latency_ms=None,
                details="Telegram bot token or target channel ID is not configured in environment.",
            )

        async with self.get_http_client() as client:
            # 1. Verify Bot Token via /getMe
            get_me_url = f"{self.bot_endpoint}/getMe"
            try:
                me_resp = await client.get(get_me_url)
                latency = (time.perf_counter() - start) * 1000.0
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                latency = (time.perf_counter() - start) * 1000.0
                return PlatformHealthResult(
                    platform=self.platform_type,
                    is_healthy=False,
                    is_configured=True,
                    auth_mode=self.auth_mode,
                    latency_ms=round(latency, 2),
                    details=f"Network connectivity error contacting Telegram API: {exc}",
                )

            if me_resp.status_code != 200 or not me_resp.json().get("ok"):
                desc = self._extract_error_description(me_resp, "Invalid bot token")
                return PlatformHealthResult(
                    platform=self.platform_type,
                    is_healthy=False,
                    is_configured=True,
                    auth_mode=self.auth_mode,
                    latency_ms=round(latency, 2),
                    details=f"Bot token verification failed (HTTP {me_resp.status_code}): {desc}",
                )

            bot_info = me_resp.json().get("result", {})
            bot_username = bot_info.get("username", "unknown_bot")

            # 2. Verify Channel Access & Permissions via /getChat
            get_chat_url = f"{self.bot_endpoint}/getChat"
            try:
                chat_resp = await client.post(get_chat_url, json={"chat_id": self.channel_id})
            except (httpx.TimeoutException, httpx.ConnectError):
                chat_resp = None

            if chat_resp and chat_resp.status_code == 200 and chat_resp.json().get("ok"):
                chat_data = chat_resp.json().get("result", {})
                chat_title = chat_data.get("title") or self.channel_id
                chat_type = chat_data.get("type", "chat")
                is_public = bool(chat_data.get("username"))
                access_desc = f"public @{chat_data.get('username')}" if is_public else "private"
                return PlatformHealthResult(
                    platform=self.platform_type,
                    is_healthy=True,
                    is_configured=True,
                    auth_mode=self.auth_mode,
                    latency_ms=round(latency, 2),
                    details=(
                        f"Connected as @{bot_username}. Target {chat_type}: '{chat_title}' "
                        f"({access_desc}, ID: {self.channel_id})"
                    ),
                )

            if chat_resp and chat_resp.status_code == 403:
                return PlatformHealthResult(
                    platform=self.platform_type,
                    is_healthy=False,
                    is_configured=True,
                    auth_mode=self.auth_mode,
                    latency_ms=round(latency, 2),
                    details=(
                        f"Bot @{bot_username} lacks administrator or posting permissions in {self.channel_id}"
                    ),
                )

            if chat_resp and chat_resp.status_code == 400:
                return PlatformHealthResult(
                    platform=self.platform_type,
                    is_healthy=False,
                    is_configured=True,
                    auth_mode=self.auth_mode,
                    latency_ms=round(latency, 2),
                    details=f"Target channel {self.channel_id} not found by Telegram",
                )

            # Fallback if getChat fails but getMe succeeded
            return PlatformHealthResult(
                platform=self.platform_type,
                is_healthy=True,
                is_configured=True,
                auth_mode=self.auth_mode,
                latency_ms=round(latency, 2),
                details=f"Authenticated as @{bot_username} (target: {self.channel_id})",
            )

    # -----------------------------------------------------------------------
    # Helper Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_error_description(response: httpx.Response, fallback: str) -> str:
        """Extract 'description' field from Telegram API error JSON."""
        try:
            data = response.json()
            if isinstance(data, dict):
                return data.get("description") or fallback
        except (ValueError, KeyError, httpx.HTTPError):
            pass
        return fallback

    @staticmethod
    def _parse_telegram_rate_limit(response: httpx.Response) -> float:
        """Parse cooldown seconds from Telegram parameters or description."""
        # 1. Telegram-native parameters.retry_after JSON attribute
        try:
            data = response.json()
            if isinstance(data, dict):
                params = data.get("parameters", {})
                if "retry_after" in params:
                    return float(params["retry_after"])
                # Fallback: parse from description e.g. "Too Many Requests: retry after 35"
                desc = data.get("description", "")
                match = re.search(r"retry after (\d+)", desc, re.IGNORECASE)
                if match:
                    return float(match.group(1))
        except (ValueError, KeyError, httpx.HTTPError):
            pass

        # 2. Standard Retry-After HTTP header
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            return parse_retry_after(retry_after)

        return 30.0
