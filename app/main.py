"""FastAPI application entry point for AutoPost Nexus (app.main).

Complies with Master Prompt Part 1 and Part 8:
- Exactly one business REST endpoint: POST /posting
- Operational health endpoint: GET /health
- Interactive API documentation: GET /docs and GET /redoc
- Ready for: uvicorn app.main:app --host 0.0.0.0 --port 4000
"""

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas import (
    HealthResponse,
    StandardPostingRequest,
    StandardPostingResponse,
)
from app.services.posting_service import CentralPostingService, PostingService
from autopost_nexus.db.session import get_db, init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    await init_db()
    yield


app = FastAPI(
    title="Automated Multi-Platform Posting System",
    version=settings.VERSION,
    description=(
        "Production-grade Automated Multi-Platform Posting System for "
        "Dxora Technologies Recruitment Practical Test.\n\n"
        "Exposes a single business endpoint (POST /posting) that accepts a message "
        "and automatically broadcasts it across five official platforms: "
        "Bluesky, Mastodon, DEV.to, WordPress, and Telegram."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request, call_next):
    """Inject execution process latency header."""
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time-Ms"] = f"{process_time * 1000:.2f}"
    return response


@app.get(
    "/",
    include_in_schema=False,
    response_class=RedirectResponse,
)
async def root_redirect():
    """Redirect root path to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Operational Health"],
    summary="System and platform health check",
    description="Operational health check monitoring database status and 5 platform configurations.",
    status_code=status.HTTP_200_OK,
)
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    """Return operational system and platform telemetry."""
    service = PostingService(db, settings)
    health = await service.get_health_status()
    if health.status != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health


@app.post(
    "/posting",
    response_model=StandardPostingResponse,
    tags=["Business Posting Endpoint"],
    summary="Multi-platform broadcast",
    description=(
        "Publish message concurrently to all five supported platforms "
        "(Bluesky, Mastodon, DEV.to, WordPress, Telegram). "
        "Requires exactly one CTA URL and maximum 200 characters."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Multi-platform posting execution results",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Posting completed",
                        "total_platforms": 5,
                        "successful": 3,
                        "failed": 2,
                        "results": [
                            {
                                "platform": "Bluesky",
                                "status": "success",
                                "posted_url": "https://bsky.app/profile/alice.bsky.social/post/3k...",
                                "public_access": True,
                                "date": "2026-11-18",
                                "time": "15:30:00",
                                "error": None,
                            },
                            {
                                "platform": "Mastodon",
                                "status": "failed",
                                "posted_url": None,
                                "public_access": False,
                                "date": None,
                                "time": None,
                                "error": "Authentication failed",
                            },
                        ],
                    }
                }
            },
        },
        422: {
            "description": "Validation error (missing URL, invalid hostname, >200 chars, extra fields)",
        },
    },
)
async def create_posting(
    payload: StandardPostingRequest,
) -> StandardPostingResponse:
    """Publish content across all 5 platforms concurrently with isolated error handling."""
    service = CentralPostingService(settings=settings)
    return await service.broadcast(payload.message)
