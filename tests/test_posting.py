"""Comprehensive tests for POST /posting endpoint covering valid and invalid inputs."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# 1. Valid Input Scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_valid_single_platform_post(client: AsyncClient):
    """Test creating a valid post for a single platform."""
    payload = {
        "content": "Hello World! This is our first automated post on Twitter. #DxoraTech",
        "platforms": ["twitter"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert "id" in data
    assert data["content"] == payload["content"]
    assert data["status"] == "in_progress"
    assert len(data["targets"]) == 1
    assert data["targets"][0]["platform"] == "twitter"
    assert data["targets"][0]["status"] == "pending"
    assert data["targets"][0]["retry_count"] == 0


@pytest.mark.asyncio
async def test_create_valid_multi_platform_post(client: AsyncClient):
    """Test creating a valid post broadcast across multiple platforms."""
    payload = {
        "title": "Major Release 1.0",
        "content": "Broadcasting release 1.0 simultaneously across all channels!",
        "platforms": ["twitter", "linkedin", "telegram", "discord", "reddit"],
        "media_urls": ["https://example.com/assets/banner.png"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Major Release 1.0"
    assert len(data["targets"]) == 5

    platforms_created = {t["platform"] for t in data["targets"]}
    assert platforms_created == {"twitter", "linkedin", "telegram", "discord", "reddit"}


@pytest.mark.asyncio
async def test_create_valid_scheduled_post(client: AsyncClient):
    """Test creating a valid post scheduled for future execution."""
    future_time = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    payload = {
        "content": "Upcoming webinar reminder! Tune in this Friday.",
        "platforms": ["telegram", "discord"],
        "scheduled_at": future_time,
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "scheduled"
    assert data["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_idempotent_post_replay(client: AsyncClient):
    """Test that submitting the same idempotency key returns the existing post."""
    key = "test-idempotency-key-001"
    payload = {
        "content": "Idempotency test message",
        "platforms": ["telegram"],
        "idempotency_key": key,
    }

    # First request: 201 Created
    res1 = await client.post("/posting", json=payload)
    assert res1.status_code == 201
    post_id = res1.json()["id"]

    # Second identical request: 200 OK (replayed)
    res2 = await client.post("/posting", json=payload)
    assert res2.status_code == 200
    assert res2.headers.get("X-Idempotent-Replay") == "true"
    assert res2.json()["id"] == post_id


# ---------------------------------------------------------------------------
# 2. Invalid Input Scenarios (Validation Gate Verification)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_empty_content(client: AsyncClient):
    """Reject completely empty content."""
    payload = {
        "content": "",
        "platforms": ["twitter"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any("content" in str(err["loc"]) for err in errors)


@pytest.mark.asyncio
async def test_reject_whitespace_only_content(client: AsyncClient):
    """Reject content that consists solely of spaces, tabs, or newlines."""
    payload = {
        "content": "   \n\t   ",
        "platforms": ["twitter"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "cannot be empty or whitespace only" in response.text


@pytest.mark.asyncio
async def test_reject_missing_content_field(client: AsyncClient):
    """Reject payload when required content field is missing."""
    payload = {
        "platforms": ["twitter"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_empty_platforms_list(client: AsyncClient):
    """Reject empty platforms list."""
    payload = {
        "content": "Valid post content",
        "platforms": [],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_invalid_platform_name(client: AsyncClient):
    """Reject unknown or unsupported platform identifiers."""
    payload = {
        "content": "Valid content",
        "platforms": ["invalid_network_xyz"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Input should be" in response.text or "invalid_network_xyz" in response.text


@pytest.mark.asyncio
async def test_reject_duplicate_platforms(client: AsyncClient):
    """Reject duplicate platform entries in target list."""
    payload = {
        "content": "Valid content",
        "platforms": ["twitter", "twitter"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Duplicate platforms are not allowed" in response.text


@pytest.mark.asyncio
async def test_reject_twitter_character_limit_exceeded(client: AsyncClient):
    """Reject content exceeding Twitter's 280-character ceiling when Twitter is targeted."""
    long_tweet = "A" * 281
    payload = {
        "content": long_tweet,
        "platforms": ["twitter"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Content exceeds Twitter limit of 280 characters" in response.text


@pytest.mark.asyncio
async def test_allow_long_content_for_non_twitter_platforms(client: AsyncClient):
    """Content > 280 characters should succeed on platforms with higher limits (e.g. Telegram, LinkedIn)."""
    medium_post = "B" * 500  # > 280 (Twitter limit) but < 4096 (Telegram limit)
    payload = {
        "content": medium_post,
        "platforms": ["telegram", "linkedin"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 201
    assert len(response.json()["targets"]) == 2


@pytest.mark.asyncio
async def test_reject_discord_character_limit_exceeded(client: AsyncClient):
    """Reject content exceeding Discord's 2000-character ceiling."""
    long_discord_post = "C" * 2001
    payload = {
        "content": long_discord_post,
        "platforms": ["discord"],
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Content exceeds Discord limit of 2000 characters" in response.text


@pytest.mark.asyncio
async def test_reject_reddit_missing_title(client: AsyncClient):
    """Reject Reddit posting request if title is absent or blank."""
    payload = {
        "content": "Interesting discussion on Python async paradigms.",
        "platforms": ["reddit"],
        # title intentionally omitted
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Title is required when Reddit is selected" in response.text


@pytest.mark.asyncio
async def test_reject_past_scheduled_time(client: AsyncClient):
    """Reject scheduled_at timestamp that points to the past."""
    past_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    payload = {
        "content": "Throwback post",
        "platforms": ["telegram"],
        "scheduled_at": past_time,
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "scheduled_at must be a future timestamp" in response.text


@pytest.mark.asyncio
async def test_reject_malformed_scheduled_at_format(client: AsyncClient):
    """Reject unparseable datetime string."""
    payload = {
        "content": "Reminder",
        "platforms": ["telegram"],
        "scheduled_at": "not-a-valid-datetime",
    }
    response = await client.post("/posting", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 3. Swagger & Documentation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openapi_schema_generated_correctly(client: AsyncClient):
    """Verify that OpenAPI schema is properly configured and accessible."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert schema["info"]["title"] == "AutoPost Nexus API"
    assert "/posting" in schema["paths"]
    assert "/health" in schema["paths"]
    assert "post" in schema["paths"]["/posting"]
    assert "get" in schema["paths"]["/health"]


@pytest.mark.asyncio
async def test_swagger_ui_accessible(client: AsyncClient):
    """Verify that Swagger UI documentation is accessible at /docs."""
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


@pytest.mark.asyncio
async def test_root_redirects_to_swagger_docs(client: AsyncClient):
    """Verify that root path / redirects to /docs."""
    response = await client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/docs"
