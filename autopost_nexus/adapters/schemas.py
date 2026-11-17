"""Standardized schemas for platform adapter operations."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autopost_nexus.schemas.posting import PlatformType


class PlatformPostPayload(BaseModel):
    """Normalized content payload passed to a platform adapter for publishing."""

    content: str = Field(..., description="Canonical body text to publish")
    title: str | None = Field(None, description="Optional post title or headline")
    media_urls: list[str] | None = Field(default=None, description="List of image/media URLs")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Platform-specific extra metadata"
    )

    model_config = ConfigDict(frozen=True)


class PublishResult(BaseModel):
    """Standardized response schema returned upon successful publication to a platform."""

    success: bool = Field(True, description="Always True for successful publishing")
    platform: PlatformType = Field(..., description="Platform identifier")
    external_post_id: str = Field(
        ..., description="Remote ID assigned by the platform (e.g. tweet ID)"
    )
    external_url: str | None = Field(
        None, description="Direct public URL to view the published post"
    )
    latency_ms: float = Field(..., description="Execution round-trip latency in milliseconds")
    raw_response: dict[str, Any] | None = Field(
        default=None, description="Masked raw API response dictionary"
    )

    model_config = ConfigDict(frozen=True)


class PublishFailure(BaseModel):
    """Standardized response schema representing a platform publication failure."""

    success: bool = Field(False, description="Always False for publication failure")
    platform: PlatformType = Field(..., description="Platform identifier")
    error_type: str = Field(..., description="Class name of the platform exception")
    error_message: str = Field(..., description="Human-readable error explanation")
    status_code: int | None = Field(None, description="HTTP status code if applicable")
    retryable: bool = Field(
        ..., description="Whether the operation should be retried automatically"
    )
    retry_after_seconds: float | None = Field(
        None, description="Suggested backoff cooldown in seconds"
    )
    latency_ms: float = Field(..., description="Execution duration before failure in milliseconds")

    model_config = ConfigDict(frozen=True)


class PlatformValidationResult(BaseModel):
    """Outcome of pre-flight content validation against platform constraints."""

    is_valid: bool = Field(..., description="True if payload complies with platform constraints")
    platform: PlatformType = Field(..., description="Platform identifier")
    character_count: int = Field(..., description="Measured character length")
    max_characters: int = Field(..., description="Maximum allowed characters for platform")
    errors: list[str] = Field(
        default_factory=list, description="List of blocking validation errors"
    )
    warnings: list[str] = Field(default_factory=list, description="Non-blocking recommendations")

    model_config = ConfigDict(frozen=True)


class PlatformHealthResult(BaseModel):
    """Standardized diagnostic result for platform credential and connectivity checks."""

    platform: PlatformType = Field(..., description="Platform identifier")
    is_healthy: bool = Field(..., description="True if credentials authenticate successfully")
    is_configured: bool = Field(..., description="True if environment variables are populated")
    auth_mode: str = Field(..., description="Authentication mode (e.g., OAuth 1.0a, Bot Token)")
    latency_ms: float | None = Field(None, description="Diagnostic probe round-trip latency in ms")
    details: str = Field(..., description="Informative status message or error details")

    model_config = ConfigDict(frozen=True)
