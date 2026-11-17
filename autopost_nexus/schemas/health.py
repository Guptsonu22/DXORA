"""Health check and diagnostic schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    """Database connectivity diagnostic details."""

    connected: bool = Field(..., description="Whether database connection is healthy")
    dialect: str = Field(..., description="Database engine dialect")
    latency_ms: float | None = Field(None, description="Round-trip ping latency in milliseconds")
    error: str | None = Field(None, description="Error message if unhealthy")


class PlatformConfigStatus(BaseModel):
    """Configuration state for a specific target platform."""

    configured: bool = Field(..., description="Whether required credentials are provided")
    auth_mode: str = Field(
        ..., description="Authentication mode (e.g., OAuth 1.0a, Bearer, Bot Token)"
    )
    status: str = Field(..., description="Platform status indicator")


class HealthResponse(BaseModel):
    """System health and operational status response."""

    status: str = Field(..., description="Overall health state (healthy, degraded, unhealthy)")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Runtime environment")
    timestamp: datetime = Field(..., description="Timestamp of health check")
    uptime_seconds: float = Field(..., description="Uptime in seconds since process startup")
    database: DatabaseHealth = Field(..., description="Database status")
    platforms: dict[str, PlatformConfigStatus] = Field(
        ...,
        description="Configuration and readiness breakdown for each target platform",
    )
