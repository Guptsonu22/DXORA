"""FastAPI application entry point for AutoPost Nexus."""

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from autopost_nexus.config import get_settings
from autopost_nexus.db.session import get_db, init_db
from autopost_nexus.schemas.health import HealthResponse
from autopost_nexus.schemas.posting import PostingCreateRequest, PostingResponse
from autopost_nexus.services.posting_service import PostingService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    # Startup: ensure database tables are created
    await init_db()
    yield
    # Shutdown: clean up resources if needed


app = FastAPI(
    title="AutoPost Nexus API",
    version=settings.VERSION,
    description=(
        "Production-grade Automated Multi-Platform Posting System for "
        "Dxora Technologies Recruitment Practical Test.\n\n"
        "Features:\n"
        "- Multi-platform broadcast (Twitter, LinkedIn, Telegram, Discord, Reddit)\n"
        "- Strict Pydantic content & platform constraints validation\n"
        "- Idempotency & deduplication support\n"
        "- Independent per-target state tracking & partial failure isolation\n"
        "- Real-time platform connectivity & database health diagnostics"
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
    tags=["System Health & Diagnostics"],
    summary="System and platform health check",
    description="Check database connectivity, round-trip latency, and third-party platform configuration status.",
    status_code=status.HTTP_200_OK,
)
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    """Return comprehensive system health telemetry."""
    service = PostingService(db, settings)
    health = await service.get_health_status()
    if health.status != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health


@app.post(
    "/posting",
    response_model=PostingResponse,
    tags=["Posting Operations"],
    summary="Create and dispatch or schedule a post",
    description=(
        "Validate content constraints against target platforms, create post records, "
        "and dispatch across specified channels. Supports client-supplied idempotency key."
    ),
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Existing post replayed via idempotency key"},
        201: {"description": "Post successfully validated and created"},
        422: {
            "description": "Validation error (character limits, invalid platform, missing fields)"
        },
    },
)
async def create_posting(
    payload: PostingCreateRequest,
    response: Response,
    idempotency_key_header: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> PostingResponse:
    """Validate and persist a multi-platform post request."""
    # Use header idempotency key if body did not specify one
    if idempotency_key_header and not payload.idempotency_key:
        payload.idempotency_key = idempotency_key_header

    service = PostingService(db, settings)
    result, is_replay = await service.create_posting(payload)

    if is_replay:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Idempotent-Replay"] = "true"

    return result
