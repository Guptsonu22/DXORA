# Automated Multi-Platform Posting System
**Dxora Technologies — Python Practical Recruitment Test**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![HTTPX](https://img.shields.io/badge/HTTPX-async-5A5A5A.svg)](https://www.python-httpx.org/)
[![Tests Passing](https://img.shields.io/badge/tests-181%20passed%20%7C%205%20skipped-brightgreen.svg)](https://github.com/Guptsonu22/DXORA)
[![Coverage](https://img.shields.io/badge/coverage-88%25-green.svg)](https://github.com/Guptsonu22/DXORA)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 1. Project Introduction

The **Automated Multi-Platform Posting System** is a professional-grade Python backend application developed for the Dxora Technologies recruitment practical evaluation. The service exposes a single business REST endpoint (`POST /posting`) that accepts a marketing or announcement message containing a Call-to-Action (CTA) URL and broadcasts it concurrently across five major social, developer, content, and messaging networks: **Bluesky**, **Mastodon**, **DEV.to**, **WordPress**, and **Telegram**.

---

## 2. Assignment Objective

The objective of this assignment is to demonstrate:
- **Clean Software Architecture:** Modular design using the Strategy and Adapter design patterns.
- **Concurrent Asynchronous I/O:** High-throughput non-blocking fan-out execution via `asyncio.gather(*tasks, return_exceptions=True)`.
- **Fault Isolation & Resilience:** Per-platform timeouts and exception shielding to ensure that a failure, network drop, or rate-limit on one network never blocks or aborts others.
- **Strict Input Validation:** Reusable validation enforcing a 200-character ceiling, exactly one valid HTTP/HTTPS CTA URL with RFC-compliant hostnames, and forbidden client platform selection.
- **Production Readiness:** 12-factor configuration via Pydantic Settings, structured logging, secret redaction, and an exhaustive automated test suite.

---

## 3. Main Features

- **Single Canonical Business Endpoint:** Exactly one business REST endpoint (`POST http://localhost:4000/posting`).
- **Internal Platform Selection:** The client submits content only; the application internally broadcasts to all 5 platforms. Client platform selection is strictly forbidden (`extra="forbid"` $\to$ HTTP 422).
- **Asynchronous Concurrent Publishing:** Dispatches to all 5 platforms concurrently.
- **Per-Platform Timeout Protection:** Configurable timeout (default 10.0s) per platform via `asyncio.wait_for`.
- **Accurate Visibility Differentiation:** Distinguishes public permalinks from non-public destinations. Private Telegram channels suppress public URLs (`posted_url = None`, `public_access = false`).
- **Real Timestamp Extraction:** Parses actual ISO 8601, GMT, and Unix epoch timestamps returned by third-party APIs without synthetic fabrication.
- **Operational Health Diagnostics:** `GET /health` endpoint reporting database connectivity, round-trip latency, and third-party credential configuration status.
- **Interactive Documentation:** Automatic OpenAPI 3.1.0 generation, Swagger UI (`/docs`), and ReDoc (`/redoc`).

---

## 4. Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Runtime** | Python 3.11+ (tested on Python 3.14) | Modern async syntax, high-performance runtime |
| **Web Framework** | FastAPI 0.115+ | High performance, native async/await, OpenAPI generation |
| **ASGI Server** | Uvicorn 0.30+ | Standard high-throughput ASGI server |
| **Validation & Schemas** | Pydantic v2 & Pydantic Settings | Strict type enforcement, zero-copy parsing, 12-factor env management |
| **HTTP Client** | HTTPX 0.27+ | Asynchronous HTTP/1.1 and HTTP/2 client with connection pooling |
| **Testing Engine** | pytest 8.4+, pytest-asyncio, respx | Wire-level HTTP mocking without monkeypatching |
| **Code Quality** | Ruff 0.17+ | Blazing fast linter and formatter enforcing PEP 8 |

---

## 5. Architecture Overview

The system follows a layered, hexagonal-inspired architecture:

```
                      ┌─────────────────────────────────────────┐
                      │           Client HTTP Request           │
                      │    POST http://localhost:4000/posting   │
                      └────────────────────┬────────────────────┘
                                           │
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │        FastAPI Validation Layer         │
                      │   - Length <= 200 chars                 │
                      │   - Exactly 1 CTA URL (HTTP/HTTPS)      │
                      │   - Valid RFC Hostname                  │
                      │   - extra='forbid' (No platform param)  │
                      └────────────────────┬────────────────────┘
                                           │
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │         Central Posting Service         │
                      │         (Concurrent Orchestrator)       │
                      └───────┬─────────────────────────┬───────┘
                              │                         │
     ┌────────────────────────┼─────────────────────────┼────────────────────────┐
     │ (asyncio.gather)       │ (asyncio.gather)        │ (asyncio.gather)       │
     ▼                        ▼                         ▼                        ▼
┌──────────────┐       ┌──────────────┐          ┌──────────────┐         ┌──────────────┐
│   Bluesky    │       │   Mastodon   │          │    DEV.to    │         │  WordPress   │ ... Telegram
│ AT Protocol  │       │ OAuth Bearer │          │   API Key    │         │ Application  │
│ createRecord │       │ /api/v1/stat │          │ /api/article │         │ Password     │
└──────────────┘       └──────────────┘          └──────────────┘         └──────────────┘
```

---

## 6. Folder Structure

```text
automated-multi-platform-posting/
├── app/                               # Standard production application package
│   ├── __init__.py
│   ├── main.py                        # FastAPI application & REST route definitions
│   ├── schemas.py                     # Pydantic models & URL validation engine
│   ├── config.py                      # Pydantic Settings configuration loader
│   ├── platforms/                     # Platform adapter strategy implementations
│   │   ├── __init__.py
│   │   ├── base.py                    # BasePlatformAdapter abstract base class
│   │   ├── bluesky.py                 # Bluesky AT Protocol XRPC adapter
│   │   ├── mastodon.py                # Mastodon REST API v1 adapter
│   │   ├── devto.py                   # DEV.to Forem API v1 adapter
│   │   ├── wordpress.py               # WordPress REST API v2 adapter
│   │   └── telegram.py                # Telegram Bot API adapter
│   └── services/
│       ├── __init__.py
│       └── posting_service.py         # CentralPostingService fan-out orchestrator
│
├── autopost_nexus/                    # Core modular engine & persistence module
│   ├── adapters/                      # Complete adapter implementations & exceptions
│   ├── schemas/                       # Request/response schemas & validation
│   ├── services/                      # Business services & central coordinator
│   └── db/                            # Optional database models, session, repo
│
├── tests/                             # Comprehensive test suite (186 collected)
│   ├── __init__.py
│   ├── conftest.py                    # Pytest fixtures & async SQLite test database
│   ├── test_validation.py             # 10 input validation cases (Part 4)
│   ├── test_platforms.py              # Unified mocked platform test suite (Part 9)
│   ├── test_central_posting_service.py# Concurrency, timeout & fault isolation tests
│   ├── test_bluesky_adapter.py        # Dedicated Bluesky AT Protocol tests
│   ├── test_mastodon_adapter.py       # Dedicated Mastodon OAuth tests
│   ├── test_devto_adapter.py          # Dedicated DEV.to API tests
│   ├── test_wordpress_adapter.py      # Dedicated WordPress REST tests
│   ├── test_telegram_adapter.py       # Dedicated Telegram Bot API tests
│   ├── test_startup_and_swagger.py    # Startup, OpenAPI schema & Swagger UI tests
│   ├── test_health.py                 # Operational telemetry tests
│   ├── test_posting.py                # Legacy targeted post persistence tests
│   └── test_live_integration.py       # Optional live integration tests (opt-in)
│
├── docs/                              # Project specification documents
│   ├── 01_PRD.md
│   ├── 02_TRD.md
│   ├── 03_APP_FLOW.md
│   ├── 04_UI_UX_DESIGN_BRIEF.md
│   ├── 05_BACKEND_SCHEMA.md
│   └── 06_IMPLEMENTATION_PLAN.md
│
├── evidence/                          # Verification audit trail & documentation
│   ├── test_execution_log.txt         # Full terminal pytest execution output
│   ├── sample_responses.json          # Real JSON responses for all outcome states
│   └── SCREENSHOT_GUIDE.md            # Step-by-step instructions for 6 screenshots
│
├── .env.example                       # Documented environment variable template
├── .gitignore                         # Strict exclusion of .env, caches, and binaries
├── requirements.txt                   # Locked project dependencies
├── pyproject.toml                     # Pytest, Coverage, and Ruff configurations
├── run.py                             # Development server launch script (Port 4000)
└── README.md                          # Master project documentation
```

---

## 7. Platform Integration Details

### 1. Bluesky
- **Protocol:** AT Protocol XRPC.
- **Authentication:** `POST https://bsky.social/xrpc/com.atproto.server.createSession` using handle/identifier and App Password.
- **Publishing:** `POST https://bsky.social/xrpc/com.atproto.repo.createRecord` (`app.bsky.feed.post`).
- **URL Extraction:** Extracts AT URI (`at://did:plc:.../app.bsky.feed.post/<rkey>`) and resolves public web permalink `https://bsky.app/profile/<handle>/post/<rkey>`.
- **Rich Text:** Automatically computes UTF-8 byte offsets for facets (links and hashtags).

### 2. Mastodon
- **API:** Mastodon REST API v1.
- **Authentication:** OAuth 2.0 Bearer token in `Authorization: Bearer <token>` header.
- **Publishing:** `POST <instance>/api/v1/statuses` with `visibility="public"` and idempotency key.
- **URL Extraction:** Extracts canonical status `url` (with fallback to `uri`).
- **Rate Limits:** Parses `X-RateLimit-Reset` ISO 8601 headers for backoff computation.

### 3. DEV.to
- **API:** Forem API v1.
- **Authentication:** `api-key: <token>` header.
- **Publishing:** `POST https://dev.to/api/articles` with `{"article": {"published": true, ...}}`.
- **Title & Body Synthesis:** Generates a clean headline from the message text and formats a Markdown article body featuring the CTA button.
- **Draft Rejection Gate:** Strictly validates that `published == True`; rejects draft articles to avoid false success claims.

### 4. WordPress
- **API:** WordPress REST API v2 (`/wp-json/wp/v2/posts`).
- **Authentication:** HTTP Basic Auth with WordPress Application Password (`base64(username:app_password)`).
- **Publishing:** `POST <site>/wp-json/wp/v2/posts` with `status="publish"`.
- **Title & Body Synthesis:** Extracts post title from opening sentence and renders HTML content with CTA hyperlink.
- **Inaccessible Sites:** Gracefully catches connection drops and DNS failures.

### 5. Telegram
- **API:** Telegram Bot API (`https://api.telegram.org/bot<token>`).
- **Authentication:** Path-based bot token.
- **Publishing:** `POST /sendMessage` with `chat_id` and Markdown formatting.
- **Public vs. Private Channels:** If the target channel has a public `@username`, constructs public web link `https://t.me/<username>/<message_id>`. For private channel IDs (e.g. `-100...`), public link is accurately suppressed (`posted_url = None`, `public_access = false`).

---

## 8. Official API Documentation Links

- **Bluesky AT Protocol:** [https://docs.bsky.app/](https://docs.bsky.app/)
- **Mastodon API:** [https://docs.joinmastodon.org/methods/statuses/](https://docs.joinmastodon.org/methods/statuses/)
- **DEV.to (Forem) API:** [https://developers.forem.com/api/v1](https://developers.forem.com/api/v1)
- **WordPress REST API:** [https://developer.wordpress.org/rest-api/reference/posts/](https://developer.wordpress.org/rest-api/reference/posts/)
- **Telegram Bot API:** [https://core.telegram.org/bots/api](https://core.telegram.org/bots/api)

---

## 9. Prerequisites

- Python 3.11, 3.12, 3.13, or 3.14
- Git
- Internet connectivity (for initial dependency installation)

---

## 10. Installation Instructions

```bash
# 1. Clone the repository
git clone https://github.com/Guptsonu22/DXORA.git
cd DXORA
```

---

## 11. Virtual Environment Setup

```bash
# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell):
python -m venv .venv
.venv\Scripts\Activate.ps1
```

---

## 12. Dependencies Installation

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 13. Environment Variable Configuration

Copy the template file:
```bash
cp .env.example .env
```

The `.env` file should be populated with the platform credentials you wish to activate:
```env
# Server Runtime
SERVER_HOST=0.0.0.0
SERVER_PORT=4000
DEBUG=false

# 1. Bluesky
BLUESKY_IDENTIFIER=your-handle.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
BLUESKY_SERVICE_URL=https://bsky.social

# 2. Mastodon
MASTODON_INSTANCE_URL=https://mastodon.social
MASTODON_ACCESS_TOKEN=your_oauth_access_token

# 3. DEV.to
DEVTO_API_KEY=your_devto_api_key

# 4. WordPress
WORDPRESS_SITE_URL=https://your-wordpress-site.com
WORDPRESS_USERNAME=your_username
WORDPRESS_APP_PASSWORD=xxxx xxxx xxxx xxxx

# 5. Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHANNEL_ID=@your_channel_username
```

---

## 14. Platform Account Configuration Guide

### Bluesky
1. Log in to [bsky.app](https://bsky.app/).
2. Navigate to **Settings** $\to$ **App Passwords**.
3. Click **Add App Password**, name it `AutoPost Nexus`, and copy the 16-character generated password.
4. Set `BLUESKY_IDENTIFIER` to your handle and `BLUESKY_APP_PASSWORD` to the generated password.

### Mastodon
1. Log in to your Mastodon instance (e.g. `mastodon.social`).
2. Go to **Preferences** $\to$ **Development** $\to$ **New Application**.
3. Name the application and grant the `write:statuses` and `read:accounts` scopes.
4. Copy the generated **Access Token** into `MASTODON_ACCESS_TOKEN`.

### DEV.to
1. Log in to [dev.to](https://dev.to/).
2. Navigate to **Settings** $\to$ **Extensions**.
3. Scroll to **DEV Community API Keys**, enter a description, and generate a new key.
4. Copy the key into `DEVTO_API_KEY`.

### WordPress
1. Log in to your WordPress Admin dashboard (`/wp-admin`).
2. Go to **Users** $\to$ **Profile**.
3. Scroll down to **Application Passwords**, enter `AutoPost Nexus`, and click **Add New Application Password**.
4. Copy the 24-character password into `WORDPRESS_APP_PASSWORD`.

### Telegram
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the prompts to create your bot and obtain the Bot Token.
3. Create a public channel or private channel, and add your bot as an **Administrator** with permission to **Post Messages**.
4. Set `TELEGRAM_BOT_TOKEN` to the token, and `TELEGRAM_CHANNEL_ID` to `@your_channel` or the numeric chat ID.

---

## 15. Server Startup

Start the server using either the convenience runner script or Uvicorn directly:

```bash
# Using convenience script:
python run.py

# Or directly with Uvicorn:
uvicorn app.main:app --host 0.0.0.0 --port 4000 --reload
```

---

## 16. Swagger Documentation

Once the server is running on port 4000:
- **Interactive Swagger UI:** [http://localhost:4000/docs](http://localhost:4000/docs)
- **ReDoc Documentation:** [http://localhost:4000/redoc](http://localhost:4000/redoc)
- **OpenAPI Schema:** [http://localhost:4000/openapi.json](http://localhost:4000/openapi.json)

---

## 17. API Request Examples

### Single Business Endpoint: `POST /posting`

#### Using cURL:
```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Check out our latest business platform and grow your online visibility. https://example.com"
  }'
```

#### Using Python HTTPX:
```python
import httpx

payload = {
    "message": "Check out our latest business platform and grow your online visibility. https://example.com"
}

with httpx.Client() as client:
    response = client.post("http://localhost:4000/posting", json=payload)
    print(response.json())
```

---

## 18. Sample Responses

### 18.1 Success Response (`200 OK`)
```json
{
  "success": true,
  "message": "Posting completed successfully across all platforms",
  "total_platforms": 5,
  "successful": 5,
  "failed": 0,
  "results": [
    {
      "platform": "Bluesky",
      "status": "success",
      "posted_url": "https://bsky.app/profile/alice.bsky.social/post/3k123456789",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:30:00",
      "error": null
    },
    {
      "platform": "Mastodon",
      "status": "success",
      "posted_url": "https://mastodon.social/@alice/112233445566",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:30:01",
      "error": null
    },
    {
      "platform": "DEV.to",
      "status": "success",
      "posted_url": "https://dev.to/alice/check-out-our-latest-business-platform-abc",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:30:02",
      "error": null
    },
    {
      "platform": "WordPress",
      "status": "success",
      "posted_url": "https://mysite.com/2026/11/check-out-our-latest-business-platform/",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:30:03",
      "error": null
    },
    {
      "platform": "Telegram",
      "status": "success",
      "posted_url": "https://t.me/dxora_channel/789",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:30:04",
      "error": null
    }
  ]
}
```

### 18.2 Partial Failure Response (`200 OK`)
```json
{
  "success": true,
  "message": "Posting completed",
  "total_platforms": 5,
  "successful": 3,
  "failed": 2,
  "results": [
    {
      "platform": "Bluesky",
      "status": "success",
      "posted_url": "https://bsky.app/profile/alice.bsky.social/post/3k987654321",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:35:10",
      "error": null
    },
    {
      "platform": "Mastodon",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Authentication failed (HTTP 401): Invalid OAuth access token"
    },
    {
      "platform": "DEV.to",
      "status": "success",
      "posted_url": "https://dev.to/alice/announcement-new-feature-xyz",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:35:12",
      "error": null
    },
    {
      "platform": "WordPress",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Platform 'wordpress' is not configured with valid credentials."
    },
    {
      "platform": "Telegram",
      "status": "success",
      "posted_url": "https://t.me/dxora_channel/790",
      "public_access": true,
      "date": "2026-11-18",
      "time": "14:35:14",
      "error": null
    }
  ]
}
```

---

## 19. Validation Rules (Part 4)

The application implements strict Pydantic v2 validation logic (`StandardPostingRequest`):

| Rule | Threshold / Constraint | Error Behavior |
|---|---|---|
| **Non-Empty Message** | Cannot be empty or whitespace only | HTTP 422: `"Message cannot be empty or whitespace only."` |
| **Length Ceiling** | Maximum 200 characters including URL | HTTP 422: `"Message length (N characters) exceeds maximum allowed length of 200."` |
| **CTA URL Count** | Exactly 1 CTA URL required | HTTP 422: `"Message must contain exactly one CTA URL (HTTP or HTTPS). None found."` or `"Message contains N URLs. Exactly one CTA URL is permitted."` |
| **URL Protocol** | Only HTTP and HTTPS | HTTP 422: `"Unsupported URL scheme 'ftp'. Only HTTP and HTTPS URLs are permitted."` |
| **Hostname Validity** | RFC domain labels, TLD $\ge 2$ chars, or valid IPv4/localhost | HTTP 422: `"URL '...' is missing a valid hostname."` |
| **Forbidden Fields** | `extra="forbid"`: Client platform selection prohibited | HTTP 422: `"Extra inputs are not permitted"` on `platforms` |

---

## 20. Error Handling & Taxonomy

All third-party exceptions are mapped to a structured hierarchy rooted at `PlatformError`:

| Exception Class | HTTP Status | Description | Retryable |
|---|:---:|---|:---:|
| `PlatformAuthenticationError` | 401 / 403 | Invalid token, revoked app password, or missing permissions | No |
| `PlatformRateLimitError` | 429 | Rate limit reached; parses `Retry-After` or `X-RateLimit-Reset` | Yes (after cooldown) |
| `PlatformContentValidationError` | 400 / 422 | Content rejected by remote platform or draft status detected | No |
| `PlatformNetworkError` | — | Connection drop, DNS timeout, or unreachable endpoint | Yes |
| `PlatformServerError` | 500 / 502 / 503 | Remote third-party infrastructure error | Yes |
| `PlatformUnconfiguredError` | — | Missing environment credentials for platform | No |

---

## 21. Testing Commands

```bash
# Run the entire test suite with summary
pytest -q

# Run with verbose test-by-test breakdown
pytest -v

# Run with statement coverage report
pytest --cov=app --cov=autopost_nexus --cov-report=term-missing

# Run code style and lint check
ruff check .

# Optional: Run live integration tests (requires real credentials in .env)
ENABLE_REAL_API_TESTS=true pytest tests/test_live_integration.py -v
```

---

## 22. Known Limitations

1. **Telegram Private Channels:** In private Telegram channels without a public `@username`, Telegram does not provide a public web permalink. The system accurately marks `public_access = false` and `posted_url = None` per Part 2 and Part 6.
2. **Third-Party Rate Limits:** Free-tier accounts on DEV.to and Mastodon impose hourly API rate ceilings. In high-frequency environments, a transient 429 response is captured and reported in `error` without failing the other 4 platforms.
3. **Draft Status Enforcement:** Certain platforms (e.g. DEV.to) default to draft status if required parameters are missing; the system explicitly enforces published status verification and rejects drafts as publishing failures.

---

## 23. Security Considerations

- **Zero Secret Exposure:** API tokens and passwords are never returned in responses, exposed in URLs, or reflected in Swagger documentation.
- **Sensitive String Masking:** All logs and error outputs pass tokens through `mask_sensitive_string()` (e.g. `supe...2345`).
- **Strict `.gitignore`:** `.env` and SQLite database files are strictly ignored and prevented from committing.
- **Header Sanitization:** Authorization headers and Basic auth credentials in HTTP exceptions are stripped via `sanitize_response_text()`.
- **CORS Policy:** Standard CORS headers are enabled with configurable origin controls.

---

## 24. Integration Verification Matrix

Per Master Prompt Part 10 requirements, the verification status of each platform is explicitly documented below:

| Platform | Mocked Unit Tests (`respx`) | Live Credentials Tested | Verified Capabilities |
|---|:---:|:---:|---|
| **Bluesky** | **VERIFIED (15 Tests)** | Optional via `.env` | XRPC `createSession`, `createRecord`, rich text byte-offset facets, session refresh |
| **Mastodon** | **VERIFIED (18 Tests)** | Optional via `.env` | OAuth Bearer, `POST /statuses`, `visibility="public"`, `Idempotency-Key`, rate-limit cooldown |
| **DEV.to** | **VERIFIED (20 Tests)** | Optional via `.env` | API key auth, Markdown article synthesis, published=true enforcement, canonical URL |
| **WordPress** | **VERIFIED (22 Tests)** | Optional via `.env` | Application Passwords, Basic Auth, title auto-generation, permalink extraction, inaccessible site handling |
| **Telegram** | **VERIFIED (16 Tests)** | Optional via `.env` | Bot API token, message ID extraction, public channel URL generation, private channel URL suppression |

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
