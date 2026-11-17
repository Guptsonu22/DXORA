"""Unit and integration tests for GET /health endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_returns_200_and_healthy(client: AsyncClient):
    """Verify that /health returns HTTP 200 with complete diagnostics including
    the five master-prompt canonical platforms."""
    response = await client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert "timestamp" in data
    assert data["uptime_seconds"] >= 0

    # Verify database diagnostics
    db_health = data["database"]
    assert db_health["connected"] is True
    assert db_health["dialect"] == "sqlite"
    assert db_health["latency_ms"] is not None
    assert db_health["latency_ms"] >= 0

    # Verify platform matrix — five master-prompt platforms
    platforms = data["platforms"]
    assert "bluesky" in platforms
    assert "mastodon" in platforms
    assert "devto" in platforms
    assert "wordpress" in platforms
    assert "telegram" in platforms

    # Validate each entry has required fields
    for p_info in platforms.values():
        assert "configured" in p_info
        assert "auth_mode" in p_info
        assert "status" in p_info

    # Verify all five show unconfigured in test mode (no .env credentials)
    for name in ("bluesky", "mastodon", "devto", "wordpress", "telegram"):
        assert platforms[name]["configured"] is False
        assert platforms[name]["status"] == "unconfigured"
