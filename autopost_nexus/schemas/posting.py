"""Pydantic schemas and enums for posting operations."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlatformType(str, Enum):
    """Supported target platform destinations."""

    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    REDDIT = "reddit"
    BLUESKY = "bluesky"


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
    PlatformType.TWITTER: 280,
    PlatformType.LINKEDIN: 3000,
    PlatformType.TELEGRAM: 4096,
    PlatformType.DISCORD: 2000,
    PlatformType.REDDIT: 40000,
    PlatformType.BLUESKY: 300,
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
