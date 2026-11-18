"""Comprehensive test suite for Phase 9: Central Posting Service and Concurrent Orchestration.

Tests all requirements from Master Prompt Part 1, Part 6, Part 7, and Phase 9:
1. Concurrent execution across all 5 platforms using asyncio.gather.
2. Partial failure isolation: failures on some platforms never affect others.
3. Per-platform timeout handling: slow platform times out without cancelling others.
4. Complete failure handling: when all platforms fail, returns success=False.
5. Standardized output structures (Part 6): platform, status, posted_url, public_access, date, time, error.
6. Public permalink distinction vs private channel (Telegram).
7. Actual API timestamp parsing (ISO 8601, GMT, Unix integer).
8. End-to-end FastAPI endpoint tests on POST /posting with HTTP 200 and HTTP 422 responses.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app as app_fastapi
from autopost_nexus.adapters.base import BasePlatformAdapter
from autopost_nexus.adapters.schemas import (
    PlatformHealthResult,
    PlatformPostPayload,
    PublishResult,
)
from autopost_nexus.config import Settings
from autopost_nexus.main import app as nexus_fastapi
from autopost_nexus.schemas.posting import (
    PlatformType,
    extract_platform_date_time,
)
from autopost_nexus.services.central_posting_service import CentralPostingService

# ---------------------------------------------------------------------------
# Test Adapters for Controlled Concurrency & Failure Injection
# ---------------------------------------------------------------------------

class StubPlatformAdapter(BasePlatformAdapter):
    """Configurable stub adapter simulating specific platform outcomes."""

    def __init__(
        self,
        platform_t: PlatformType,
        configured: bool = True,
        delay_seconds: float = 0.0,
        should_fail: bool = False,
        error_msg: str = "Simulated error",
        external_url: str | None = "https://example.com/post/123",
        raw_response: dict | None = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(settings=Settings(), timeout_seconds=timeout_seconds)
        self._platform_type = platform_t
        self._configured = configured
        self._delay_seconds = delay_seconds
        self._should_fail = should_fail
        self._error_msg = error_msg
        self._external_url = external_url
        self._raw_response = raw_response or {
            "createdAt": "2026-11-18T12:00:00.000Z",
            "url": self._external_url,
        }

    @property
    def platform_type(self) -> PlatformType:
        return self._platform_type

    @property
    def max_characters(self) -> int:
        return 500

    @property
    def auth_mode(self) -> str:
        return "Stub Authentication"

    def is_configured(self) -> bool:
        return self._configured

    async def publish(self, payload: PlatformPostPayload) -> PublishResult:
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)

        if self._should_fail:
            raise RuntimeError(self._error_msg)

        return PublishResult(
            success=True,
            platform=self._platform_type,
            external_post_id="stub-id-123",
            external_url=self._external_url,
            latency_ms=10.5,
            raw_response=self._raw_response,
        )

    async def check_health(self) -> PlatformHealthResult:
        return PlatformHealthResult(
            platform=self._platform_type,
            is_healthy=self._configured,
            is_configured=self._configured,
            auth_mode=self.auth_mode,
            latency_ms=5.0,
            details="Stub health",
        )


# ---------------------------------------------------------------------------
# Central Posting Service Unit & Orchestration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_five_platforms_succeed_concurrently():
    """All 5 platforms succeed concurrently with verified URLs and UTC timestamps."""
    adapters = [
        StubPlatformAdapter(
            PlatformType.BLUESKY,
            external_url="https://bsky.app/profile/user/post/3k1",
            raw_response={"createdAt": "2026-11-18T14:30:00.000Z"},
        ),
        StubPlatformAdapter(
            PlatformType.MASTODON,
            external_url="https://mastodon.social/@user/112233",
            raw_response={"created_at": "2026-11-18T14:30:01.000Z"},
        ),
        StubPlatformAdapter(
            PlatformType.DEVTO,
            external_url="https://dev.to/user/post-slug-123",
            raw_response={"published_at": "2026-11-18T14:30:02Z"},
        ),
        StubPlatformAdapter(
            PlatformType.WORDPRESS,
            external_url="https://mysite.com/2026/11/post-slug",
            raw_response={"date_gmt": "2026-11-18T14:30:03"},
        ),
        StubPlatformAdapter(
            PlatformType.TELEGRAM,
            external_url="https://t.me/public_channel/55",
            raw_response={"date": int(datetime(2026, 11, 18, 14, 30, 4, tzinfo=UTC).timestamp())},
        ),
    ]

    service = CentralPostingService(adapters=adapters, per_platform_timeout=5.0)
    msg = "Check out our latest business platform and grow your online visibility. https://example.com"
    response = await service.broadcast(msg)

    assert response.success is True
    assert response.total_platforms == 5
    assert response.successful == 5
    assert response.failed == 0
    assert response.message == "Posting completed successfully across all platforms"
    assert len(response.results) == 5

    # Check each platform result complies with Part 6
    results_by_platform = {r.platform: r for r in response.results}
    assert set(results_by_platform.keys()) == {"Bluesky", "Mastodon", "DEV.to", "WordPress", "Telegram"}

    for r in results_by_platform.values():
        assert r.status == "success"
        assert r.posted_url is not None
        assert r.public_access is True
        assert r.date == "2026-11-18"
        assert r.time is not None
        assert r.error is None


@pytest.mark.asyncio
async def test_partial_failure_isolation():
    """Partial failure: 2 succeed, 2 fail with errors, 1 unconfigured.

    Overall status must be success=True per Part 7, and failures must be isolated.
    """
    adapters = [
        # 1. Success
        StubPlatformAdapter(
            PlatformType.BLUESKY,
            external_url="https://bsky.app/profile/u/post/1",
            raw_response={"createdAt": "2026-11-18T10:00:00Z"},
        ),
        # 2. Unconfigured
        StubPlatformAdapter(
            PlatformType.MASTODON,
            configured=False,
        ),
        # 3. Auth failure
        StubPlatformAdapter(
            PlatformType.DEVTO,
            should_fail=True,
            error_msg="DEV.to authentication failed (HTTP 401)",
        ),
        # 4. Success
        StubPlatformAdapter(
            PlatformType.WORDPRESS,
            external_url="https://wp.example.com/post-42",
            raw_response={"date_gmt": "2026-11-18T10:00:00"},
        ),
        # 5. Remote server error
        StubPlatformAdapter(
            PlatformType.TELEGRAM,
            should_fail=True,
            error_msg="Telegram Bot API error (HTTP 502)",
        ),
    ]

    service = CentralPostingService(adapters=adapters, per_platform_timeout=5.0)
    response = await service.broadcast("Great new update available at https://example.com/news")

    assert response.success is True
    assert response.total_platforms == 5
    assert response.successful == 2
    assert response.failed == 3
    assert response.message == "Posting completed"

    results_by_name = {r.platform: r for r in response.results}

    # Bluesky & WordPress succeeded
    assert results_by_name["Bluesky"].status == "success"
    assert results_by_name["Bluesky"].posted_url == "https://bsky.app/profile/u/post/1"
    assert results_by_name["WordPress"].status == "success"
    assert results_by_name["WordPress"].posted_url == "https://wp.example.com/post-42"

    # Mastodon failed because unconfigured
    assert results_by_name["Mastodon"].status == "failed"
    assert results_by_name["Mastodon"].posted_url is None
    assert "not configured" in results_by_name["Mastodon"].error

    # DEV.to failed because auth error
    assert results_by_name["DEV.to"].status == "failed"
    assert "authentication failed" in results_by_name["DEV.to"].error.lower()

    # Telegram failed because 502
    assert results_by_name["Telegram"].status == "failed"
    assert "502" in results_by_name["Telegram"].error


@pytest.mark.asyncio
async def test_per_platform_timeout_does_not_block_others():
    """Per-platform timeout handling: one platform stalls, other 4 finish promptly."""
    adapters = [
        # Fast platforms (0.01s)
        StubPlatformAdapter(PlatformType.BLUESKY, delay_seconds=0.01, external_url="https://bsky.app/p/1"),
        StubPlatformAdapter(PlatformType.MASTODON, delay_seconds=0.01, external_url="https://masto.social/1"),
        # Slow platform stalls for 2.0s (exceeds 0.15s per_platform_timeout)
        StubPlatformAdapter(PlatformType.DEVTO, delay_seconds=2.0),
        StubPlatformAdapter(PlatformType.WORDPRESS, delay_seconds=0.01, external_url="https://wp.com/1"),
        StubPlatformAdapter(PlatformType.TELEGRAM, delay_seconds=0.01, external_url="https://t.me/pub/1"),
    ]

    service = CentralPostingService(adapters=adapters, per_platform_timeout=0.15)
    start_time = asyncio.get_event_loop().time()
    response = await service.broadcast("Testing timeout isolation at https://example.com/timeout")
    elapsed = asyncio.get_event_loop().time() - start_time

    # Should finish around 0.15s, not 2.0s
    assert elapsed < 0.8, f"Service took {elapsed}s, timeout isolation failed!"
    assert response.success is True
    assert response.total_platforms == 5
    assert response.successful == 4
    assert response.failed == 1

    results_by_name = {r.platform: r for r in response.results}
    devto_res = results_by_name["DEV.to"]
    assert devto_res.status == "failed"
    assert "timed out after 0.1s" in devto_res.error or "timed out" in devto_res.error.lower()
    assert devto_res.posted_url is None


@pytest.mark.asyncio
async def test_total_failure_returns_success_false():
    """Total failure across all platforms returns success=False and message."""
    adapters = [
        StubPlatformAdapter(PlatformType.BLUESKY, configured=False),
        StubPlatformAdapter(PlatformType.MASTODON, configured=False),
        StubPlatformAdapter(PlatformType.DEVTO, configured=False),
        StubPlatformAdapter(PlatformType.WORDPRESS, configured=False),
        StubPlatformAdapter(PlatformType.TELEGRAM, configured=False),
    ]

    service = CentralPostingService(adapters=adapters, per_platform_timeout=5.0)
    response = await service.broadcast("Broadcast message https://example.com")

    assert response.success is False
    assert response.total_platforms == 5
    assert response.successful == 0
    assert response.failed == 5
    assert response.message == "Posting failed across all platforms"
    for r in response.results:
        assert r.status == "failed"
        assert r.posted_url is None
        assert r.public_access is False
        assert r.date is None
        assert r.time is None
        assert r.error is not None


@pytest.mark.asyncio
async def test_telegram_private_channel_public_access_is_false():
    """Master Prompt Part 2 & Part 6: Private Telegram channel post must have public_access=False."""
    adapters = [
        StubPlatformAdapter(
            PlatformType.TELEGRAM,
            external_url=None,  # Private channel produces no public link
            raw_response={"date": 1763476204},
        )
    ]
    service = CentralPostingService(adapters=adapters, per_platform_timeout=5.0)
    response = await service.broadcast("Private update https://example.com/private")

    assert response.success is True
    assert response.successful == 1
    tg_res = response.results[0]
    assert tg_res.status == "success"
    assert tg_res.posted_url is None
    assert tg_res.public_access is False  # Confirmed non-public per Part 6
    assert tg_res.date is not None
    assert tg_res.time is not None


def test_extract_platform_date_time_formats():
    """Test timestamp extraction across all five platform raw formats."""
    # 1. Bluesky createdAt (ISO)
    d, t = extract_platform_date_time({"createdAt": "2026-11-18T15:45:30.123Z"})
    assert d == "2026-11-18"
    assert t == "15:45:30"

    # 2. Mastodon created_at (ISO)
    d, t = extract_platform_date_time({"created_at": "2026-11-18T10:20:15.000Z"})
    assert d == "2026-11-18"
    assert t == "10:20:15"

    # 3. DEV.to published_at (ISO)
    d, t = extract_platform_date_time({"published_at": "2026-11-18T08:00:00Z"})
    assert d == "2026-11-18"
    assert t == "08:00:00"

    # 4. WordPress date_gmt (ISO)
    d, t = extract_platform_date_time({"date_gmt": "2026-11-18T12:00:00"})
    assert d == "2026-11-18"
    assert t == "12:00:00"

    # 5. Telegram date (Unix epoch integer)
    # 1763476204 is 2025-11-18T14:30:04 UTC (or similar deterministic epoch)
    dt_expected = datetime.fromtimestamp(1763476204, tz=UTC)
    d, t = extract_platform_date_time({"date": 1763476204})
    assert d == dt_expected.strftime("%Y-%m-%d")
    assert t == dt_expected.strftime("%H:%M:%S")

    # 6. Fallback if None or empty
    d, t = extract_platform_date_time(None)
    assert len(d) == 10
    assert len(t) == 8


# ---------------------------------------------------------------------------
# FastAPI REST Integration Tests for POST /posting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_main_posting_endpoint_success():
    """Test POST /posting on app.main:app with valid message returning HTTP 200."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "message": "Check out our latest platform and grow visibility! https://example.com"
        }
        res = await client.post("/posting", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "success" in data
        assert "message" in data
        assert data["total_platforms"] == 5
        assert "successful" in data
        assert "failed" in data
        assert len(data["results"]) == 5


@pytest.mark.asyncio
async def test_app_main_posting_endpoint_validation_errors():
    """Test POST /posting on app.main:app rejects invalid payloads with HTTP 422."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing message field
        res1 = await client.post("/posting", json={})
        assert res1.status_code == 422

        # 2. Empty message
        res2 = await client.post("/posting", json={"message": ""})
        assert res2.status_code == 422

        # 3. Message missing URL
        res3 = await client.post("/posting", json={"message": "No link provided in text"})
        assert res3.status_code == 422

        # 4. Message with multiple URLs
        res4 = await client.post(
            "/posting",
            json={"message": "Visit https://a.com and https://b.com"}
        )
        assert res4.status_code == 422

        # 5. Message > 200 chars
        res5 = await client.post(
            "/posting",
            json={"message": "Z" * 190 + " https://example.com"}
        )
        assert res5.status_code == 422

        # 6. Extra fields forbidden (client platform selection rejected)
        res6 = await client.post(
            "/posting",
            json={
                "message": "Valid text https://example.com",
                "platforms": ["twitter"],
            }
        )
        assert res6.status_code == 422


@pytest.mark.asyncio
async def test_nexus_main_posting_endpoint_standard_format():
    """Test POST /posting on autopost_nexus.main:app supports standard master prompt format."""
    transport = ASGITransport(app=nexus_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "message": "Multi-platform broadcast test message https://example.com/demo"
        }
        res = await client.post("/posting", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["total_platforms"] == 5
        assert len(data["results"]) == 5
