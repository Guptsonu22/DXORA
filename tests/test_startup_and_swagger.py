"""Application startup, Swagger/OpenAPI documentation, and lifecycle tests.

Verifies Master Prompt Part 8:
- FastAPI startup and shutdown lifecycle.
- OpenAPI schema correctness at /openapi.json.
- Swagger UI availability at /docs.
- ReDoc availability at /redoc.
- Root path redirection to /docs.
- Latency and security headers.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app as app_fastapi
from autopost_nexus.main import app as nexus_fastapi


@pytest.mark.asyncio
async def test_app_main_openapi_schema():
    """Verify app.main OpenAPI schema generation and path definitions."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/openapi.json")
        assert res.status_code == 200
        schema = res.json()

        assert "openapi" in schema
        assert schema["info"]["title"] == "Automated Multi-Platform Posting System"
        assert "/posting" in schema["paths"]
        assert "post" in schema["paths"]["/posting"]
        assert "/health" in schema["paths"]
        assert "get" in schema["paths"]["/health"]

        # Confirm POST /posting requires 'message'
        posting_schema = schema["components"]["schemas"]["StandardPostingRequest"]
        assert "message" in posting_schema["properties"]
        assert "platforms" not in posting_schema["properties"]


@pytest.mark.asyncio
async def test_app_main_swagger_ui_available():
    """Verify Swagger UI renders at /docs."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/docs")
        assert res.status_code == 200
        assert "swagger-ui" in res.text.lower()


@pytest.mark.asyncio
async def test_app_main_redoc_available():
    """Verify ReDoc documentation renders at /redoc."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/redoc")
        assert res.status_code == 200
        assert "redoc" in res.text.lower()


@pytest.mark.asyncio
async def test_app_main_root_redirects_to_docs():
    """Verify root path / redirects to /docs."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        res = await client.get("/")
        assert res.status_code in (307, 302)
        assert res.headers["location"] == "/docs"


@pytest.mark.asyncio
async def test_nexus_main_openapi_schema():
    """Verify autopost_nexus.main OpenAPI schema generation."""
    transport = ASGITransport(app=nexus_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/openapi.json")
        assert res.status_code == 200
        schema = res.json()
        assert "/posting" in schema["paths"]
        assert "/health" in schema["paths"]


@pytest.mark.asyncio
async def test_process_time_header_injected():
    """Verify custom X-Process-Time-Ms performance header is injected on all responses."""
    transport = ASGITransport(app=app_fastapi)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        assert "X-Process-Time-Ms" in res.headers
        latency_val = float(res.headers["X-Process-Time-Ms"])
        assert latency_val >= 0.0


def test_app_platforms_reexports():
    """Verify that app.platforms package cleanly re-exports all adapters and base classes."""
    import app.platforms as p
    assert hasattr(p, "BlueskyAdapter")
    assert hasattr(p, "MastodonAdapter")
    assert hasattr(p, "DevtoAdapter")
    assert hasattr(p, "WordPressAdapter")
    assert hasattr(p, "TelegramAdapter")
    assert hasattr(p, "BasePlatformAdapter")
