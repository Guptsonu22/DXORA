"""Pydantic schemas and enums for posting operations."""

import re
import urllib.parse
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlatformType(str, Enum):
    """Supported target platform destinations (master-prompt canonical set + legacy)."""

    # --- Five required platforms per master prompt ---
    BLUESKY = "bluesky"
    MASTODON = "mastodon"
    DEVTO = "devto"
    WORDPRESS = "wordpress"
    TELEGRAM = "telegram"

    # --- Retained for backwards-compat with existing tests ---
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    DISCORD = "discord"
    REDDIT = "reddit"


class PostStatus(str, Enum):
    """Aggregate lifecycle states for a multi-platform post."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class TargetStatus(str, Enum):
    """Per-platform target delivery states."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


# Platform-specific character and constraint thresholds
PLATFORM_LIMITS = {
    PlatformType.BLUESKY: 300,
    PlatformType.MASTODON: 500,
    PlatformType.DEVTO: 65536,   # DEV.to: article body has no hard cap in practice
    PlatformType.WORDPRESS: 65536,  # WordPress REST API: no hard cap
    PlatformType.TELEGRAM: 4096,
    # Legacy entries kept for backwards-compat
    PlatformType.TWITTER: 280,
    PlatformType.LINKEDIN: 3000,
    PlatformType.DISCORD: 2000,
    PlatformType.REDDIT: 40000,
}


class PostingCreateRequest(BaseModel):
    """Request payload for creating and dispatching/scheduling a post."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The main text content to broadcast across selected platforms.",
        examples=[
            "Excited to launch our new Automated Multi-Platform Posting System! 🚀 #DxoraTech"
        ],
    )
    platforms: list[PlatformType] = Field(
        ...,
        min_length=1,
        description="List of target platform identifiers.",
        examples=[[PlatformType.TWITTER, PlatformType.TELEGRAM, PlatformType.DISCORD]],
    )
    title: str | None = Field(
        None,
        max_length=300,
        description="Optional title/headline (mandatory if Reddit is in platforms).",
        examples=["Product Launch Announcement"],
    )
    media_urls: list[str] | None = Field(
        default=None,
        description="Optional list of image or attachment URLs to include.",
        examples=[["https://example.com/banner.png"]],
    )
    scheduled_at: datetime | None = Field(
        default=None,
        description="Optional UTC timestamp to schedule future dispatch.",
        examples=[None],
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=64,
        description="Optional unique client idempotency key to prevent duplicate broadcasts.",
        examples=["b7f32e60-4965-4f35-9799-a9a3b2b4129e"],
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_blank(cls, v: str) -> str:
        """Ensure content does not consist solely of whitespace."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Content cannot be empty or whitespace only.")
        return stripped

    @field_validator("platforms")
    @classmethod
    def validate_unique_platforms(cls, v: list[PlatformType]) -> list[PlatformType]:
        """Ensure no duplicate platforms are provided."""
        if not v:
            raise ValueError("At least one target platform must be specified.")
        if len(v) != len(set(v)):
            duplicates = [item for item in set(v) if v.count(item) > 1]
            raise ValueError(
                f"Duplicate platforms are not allowed: {[d.value for d in duplicates]}"
            )
        return v

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_future(cls, v: datetime | None) -> datetime | None:
        """Ensure scheduled_at timestamp is in the future."""
        if v is not None:
            # Handle naive datetime by assuming UTC
            if v.tzinfo is None:
                v = v.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            if v <= now:
                raise ValueError("scheduled_at must be a future timestamp.")
        return v

    @model_validator(mode="after")
    def validate_platform_specific_rules(self) -> "PostingCreateRequest":
        """Apply strict platform-level constraints across fields."""
        content_len = len(self.content)

        # Twitter character limit check
        if PlatformType.TWITTER in self.platforms:
            max_twitter = PLATFORM_LIMITS[PlatformType.TWITTER]
            if content_len > max_twitter:
                raise ValueError(
                    f"Content exceeds Twitter limit of {max_twitter} characters (received {content_len})."
                )

        # Discord character limit check
        if PlatformType.DISCORD in self.platforms:
            max_discord = PLATFORM_LIMITS[PlatformType.DISCORD]
            if content_len > max_discord:
                raise ValueError(
                    f"Content exceeds Discord limit of {max_discord} characters (received {content_len})."
                )

        # LinkedIn character limit check
        if PlatformType.LINKEDIN in self.platforms:
            max_linkedin = PLATFORM_LIMITS[PlatformType.LINKEDIN]
            if content_len > max_linkedin:
                raise ValueError(
                    f"Content exceeds LinkedIn limit of {max_linkedin} characters (received {content_len})."
                )

        # Bluesky character limit check (300 graphemes)
        if PlatformType.BLUESKY in self.platforms:
            max_bluesky = PLATFORM_LIMITS[PlatformType.BLUESKY]
            if content_len > max_bluesky:
                raise ValueError(
                    f"Content exceeds Bluesky limit of {max_bluesky} characters (received {content_len})."
                )

        # Mastodon character limit check (500 chars)
        if PlatformType.MASTODON in self.platforms:
            max_mastodon = PLATFORM_LIMITS[PlatformType.MASTODON]
            if content_len > max_mastodon:
                raise ValueError(
                    f"Content exceeds Mastodon limit of {max_mastodon} characters (received {content_len})."
                )

        # Reddit requires a title
        if PlatformType.REDDIT in self.platforms and (not self.title or not self.title.strip()):
            raise ValueError("Title is required when Reddit is selected as a target platform.")

        return self


class TargetStatusResponse(BaseModel):
    """Detailed delivery status for an individual platform target."""

    id: str = Field(..., description="Target UUID")
    platform: PlatformType = Field(..., description="Platform identifier")
    status: TargetStatus = Field(..., description="Current delivery status")
    external_post_id: str | None = Field(None, description="External ID from remote API")
    external_url: str | None = Field(None, description="Public direct URL to the published post")
    retry_count: int = Field(0, description="Number of retry attempts executed")
    error_message: str | None = Field(None, description="Error reason if failed")
    published_at: datetime | None = Field(None, description="Timestamp of successful broadcast")

    model_config = ConfigDict(from_attributes=True)


class PostingResponse(BaseModel):
    """Comprehensive response for a post including all platform target states."""

    id: str = Field(..., description="Post UUID")
    title: str | None = Field(None, description="Post title")
    content: str = Field(..., description="Post content")
    status: PostStatus = Field(..., description="Overall post status")
    idempotency_key: str | None = Field(None, description="Idempotency key")
    scheduled_at: datetime | None = Field(None, description="Scheduled execution timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    targets: list[TargetStatusResponse] = Field(
        default_factory=list,
        description="List of target platform statuses",
    )

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Master Prompt Canonical Platform Display Names
# ===========================================================================

PLATFORM_DISPLAY_NAMES: dict[PlatformType, str] = {
    PlatformType.BLUESKY: "Bluesky",
    PlatformType.MASTODON: "Mastodon",
    PlatformType.DEVTO: "DEV.to",
    PlatformType.WORDPRESS: "WordPress",
    PlatformType.TELEGRAM: "Telegram",
}


# ===========================================================================
# Master Prompt Part 1 & Part 4: Reusable Message & URL Validation Logic
# ===========================================================================

URL_CANDIDATE_REGEX = re.compile(
    r'(?:[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"]*|(?:mailto|tel|urn|sms|geo|data|javascript):[^\s<>"]+|www\.[^\s<>"]+)',
    re.IGNORECASE,
)

TRAILING_PUNCTUATION = ".,;:!?'\"`"


def clean_candidate_url(raw_url: str) -> str:
    """Trim surrounding quotes/brackets and trailing punctuation from URL token."""
    cleaned = raw_url.strip()

    # Strip matching outer brackets or quotes enclosing the URL
    if (
        (cleaned.startswith("(") and cleaned.endswith(")"))
        or (cleaned.startswith("[") and cleaned.endswith("]"))
        or (cleaned.startswith("{") and cleaned.endswith("}"))
        or (cleaned.startswith('"') and cleaned.endswith('"'))
        or (cleaned.startswith("'") and cleaned.endswith("'"))
    ):
        cleaned = cleaned[1:-1].strip()

    while cleaned and cleaned[-1] in TRAILING_PUNCTUATION:
        cleaned = cleaned[:-1]

    # Handle closing brackets when no matching opener is inside the URL
    if cleaned.endswith(")") and "(" not in cleaned:
        cleaned = cleaned[:-1]
    if cleaned.endswith("]") and "[" not in cleaned:
        cleaned = cleaned[:-1]
    if cleaned.endswith("}") and "{" not in cleaned:
        cleaned = cleaned[:-1]

    return cleaned


def is_valid_hostname(hostname: str) -> bool:
    """Validate that hostname conforms to RFC domain or IP standards."""
    if not hostname or len(hostname) > 253:
        return False

    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        return True

    # IPv4 numerical address check
    parts = hostname.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return all(0 <= int(p) <= 255 for p in parts)

    # Domain name check: must consist of at least two dot-separated labels (domain.tld)
    if len(parts) < 2:
        return False

    # TLD must be alphabetic and at least 2 characters
    tld = parts[-1]
    if not tld.isalpha() or len(tld) < 2:
        return False

    label_regex = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
    for label in parts[:-1]:
        if not label or not label_regex.match(label):
            return False

    return True


def validate_posting_message(message: str) -> tuple[str, str]:
    """Validate posting message per master prompt Part 1 & Part 4 specifications.

    Requirements:
    - Message must not be empty or whitespace only.
    - Maximum length: 200 characters including URL.
    - Exactly one CTA URL.
    - Only HTTP and HTTPS URLs.
    - URL must have a valid hostname.
    - Reject multiple URLs.
    - Reject invalid URL structures.

    Returns:
        tuple[str, str]: (cleaned_message, extracted_cta_url)

    Raises:
        ValueError with clear explanatory error message on validation failure.
    """
    if not isinstance(message, str):
        raise TypeError("Message must be a string.")

    cleaned_message = message.strip()
    if not cleaned_message:
        raise ValueError("Message cannot be empty or whitespace only.")

    if len(message) > 200:
        raise ValueError(
            f"Message length ({len(message)} characters) exceeds maximum allowed length of 200 characters."
        )

    raw_candidates = URL_CANDIDATE_REGEX.findall(cleaned_message)
    if not raw_candidates:
        raise ValueError("Message must contain exactly one CTA URL (HTTP or HTTPS). None found.")

    cleaned_candidates = [
        cleaned
        for c in raw_candidates
        if (cleaned := clean_candidate_url(c))
    ]

    if not cleaned_candidates:
        raise ValueError("Message must contain exactly one CTA URL (HTTP or HTTPS). None found.")

    if len(cleaned_candidates) > 1:
        raise ValueError(
            f"Message contains {len(cleaned_candidates)} URLs. Exactly one CTA URL is permitted."
        )

    candidate = cleaned_candidates[0]

    try:
        parsed = urllib.parse.urlparse(candidate)
    except Exception as exc:
        raise ValueError(f"Malformed URL structure: {candidate}") from exc

    if not parsed.scheme:
        raise ValueError(
            f"URL '{candidate}' is missing a protocol scheme. Only HTTP and HTTPS URLs are permitted."
        )

    scheme_lower = parsed.scheme.lower()
    if scheme_lower not in ("http", "https"):
        raise ValueError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only HTTP and HTTPS URLs are permitted."
        )

    if not parsed.netloc or not parsed.hostname:
        raise ValueError(f"URL '{candidate}' is missing a valid hostname.")

    hostname = parsed.hostname
    if not is_valid_hostname(hostname):
        raise ValueError(f"URL '{candidate}' contains an invalid hostname '{hostname}'.")

    return cleaned_message, candidate


# ===========================================================================
# Master Prompt Part 1 & Part 4: Standard Business REST Request Schema
# ===========================================================================

class StandardPostingRequest(BaseModel):
    """Business REST request payload strictly adhering to master prompt Part 1 & Part 4.

    The client must NOT select platforms. Platform selection happens internally.
    Any extra fields (such as 'platforms') are strictly forbidden and rejected with HTTP 422.
    """

    message: str = Field(
        ...,
        description="Text message containing exactly one valid CTA URL (max 200 characters).",
        examples=[
            "Check out our latest business platform and grow your online visibility. https://example.com"
        ],
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Validate length, URL presence, scheme, hostname, and count."""
        cleaned_msg, _ = validate_posting_message(v)
        return cleaned_msg


# ===========================================================================
# Master Prompt Part 6: Standardized Platform Response Schema
# ===========================================================================

class StandardPlatformResult(BaseModel):
    """Standardized response schema returned by every platform per master prompt Part 6."""

    platform: str = Field(
        ...,
        description="Platform display name (Bluesky, Mastodon, DEV.to, WordPress, Telegram)",
        examples=["Bluesky"],
    )
    status: Literal["success", "failed"] = Field(
        ...,
        description="Execution status ('success' or 'failed')",
        examples=["success"],
    )
    posted_url: str | None = Field(
        None,
        description="Actual public URL to the post if verified and accessible, else None",
        examples=["https://bsky.app/profile/alice.bsky.social/post/3k..."],
    )
    public_access: bool = Field(
        False,
        description="Confirmed public accessibility without special authentication",
        examples=[True],
    )
    date: str | None = Field(
        None,
        description="Publication date formatted as YYYY-MM-DD (UTC), or None if failed",
        examples=["2026-11-18"],
    )
    time: str | None = Field(
        None,
        description="Publication time formatted as HH:MM:SS (UTC), or None if failed",
        examples=["15:30:00"],
    )
    error: str | None = Field(
        None,
        description="Human-readable error description if failed, else None",
        examples=[None],
    )

    model_config = ConfigDict(frozen=True)


# ===========================================================================
# Master Prompt Part 7: Aggregated Posting Response Schema
# ===========================================================================

class StandardPostingResponse(BaseModel):
    """Aggregated posting response across all platforms per master prompt Part 7."""

    success: bool = Field(
        ...,
        description="True if at least one platform succeeded, False if all failed",
        examples=[True],
    )
    message: str = Field(
        ...,
        description="Summary description of the execution outcome",
        examples=["Posting completed"],
    )
    total_platforms: int = Field(
        5,
        description="Total number of target platforms evaluated",
        examples=[5],
    )
    successful: int = Field(
        ...,
        description="Count of platforms published successfully",
        examples=[3],
    )
    failed: int = Field(
        ...,
        description="Count of platforms that failed or timed out",
        examples=[2],
    )
    results: list[StandardPlatformResult] = Field(
        default_factory=list,
        description="Standardized individual platform results",
    )

    model_config = ConfigDict(frozen=True)


# ===========================================================================
# Date & Time Extraction Utility from Actual API Responses
# ===========================================================================

def extract_platform_date_time(raw_response: dict[str, Any] | None) -> tuple[str, str]:
    """Extract actual publication UTC date and time from remote platform raw response.

    Extracts:
    - Bluesky: createdAt (ISO 8601)
    - Mastodon: created_at (ISO 8601)
    - DEV.to: published_at (ISO 8601)
    - WordPress: date_gmt or date (ISO 8601)
    - Telegram: date (Unix epoch integer timestamp)

    Returns:
        tuple[str, str]: (YYYY-MM-DD, HH:MM:SS) in UTC.
    """
    if not raw_response or not isinstance(raw_response, dict):
        now = datetime.now(UTC)
        return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")

    for key in ("createdAt", "created_at", "published_at", "date_gmt", "date"):
        val = raw_response.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val, tz=UTC)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
        if isinstance(val, str) and val.strip():
            iso_str = val.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(iso_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                else:
                    dt = dt.astimezone(UTC)
                return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
            except ValueError:
                continue

    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")

