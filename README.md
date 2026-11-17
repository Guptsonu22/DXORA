# Automated Multi-Platform Posting System
**Dxora Technologies — Python Practical Recruitment Test**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![HTTPX](https://img.shields.io/badge/HTTPX-async-5A5A5A.svg)](https://www.python-httpx.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 1. Project Overview & Objective

The **Automated Multi-Platform Posting System** is a production-grade Python backend service built for the **Dxora Technologies** recruitment practical assessment.

The application allows a client to submit a single message with an embedded Call-to-Action (CTA) URL, which is then automatically formatted, validated, and broadcast concurrently across **five major publishing platforms**:
1. **Bluesky** (via AT Protocol XRPC)
2. **Mastodon** (via official REST API v1)
3. **DEV.to** (via Forem API v1)
4. **WordPress** (via WP REST API v2)
5. **Telegram** (via Bot API)

### Key Architectural Mandates
- **No Client Platform Selection:** Platform selection happens entirely internal to the application.
- **Strict Input Validation:** Messages must be $\le 200$ characters and contain **exactly one** valid HTTP/HTTPS Call-to-Action URL with a valid hostname.
- **Independent Execution & Fault Isolation:** One platform failing, timing out, or lacking credentials must **never** prevent other platforms from executing.
- **Genuine Output & No Fake Results:** Real publication permalinks and API response statuses are returned without fabrication.

---

## 2. Technology Stack

- **Language:** Python 3.11+ (Developed & tested on Python 3.14)
- **API Framework:** [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- **Validation:** [Pydantic v2](https://docs.pydantic.dev/) + [Pydantic-Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- **HTTP Client:** [HTTPX](https://www.python-httpx.org/) (AsyncIO connection pooling, per-platform timeouts)
- **Testing:** [pytest](https://docs.pytest.org/), [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio), [respx](https://lundberg.github.io/respx/) (wire-mocking)
- **Environment Management:** [python-dotenv](https://github.com/theskumar/python-dotenv)

---

## 3. Project Architecture & Directory Layout

```text
automated-multi-platform-posting/
│
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI application entry point & routes
│   ├── schemas.py               # Pydantic v2 request/response models & URL validation
│   ├── config.py                # 12-factor Pydantic Settings & credentials management
│   │
│   ├── platforms/               # Strategy Pattern platform adapters
│   │   ├── __init__.py
│   │   ├── base.py              # BasePlatform abstract class
│   │   ├── bluesky.py           # AT Protocol XRPC integration
│   │   ├── mastodon.py          # Mastodon REST API v1 integration
│   │   ├── devto.py             # DEV.to (Forem) API integration
│   │   ├── wordpress.py         # WordPress REST API v2 integration
│   │   └── telegram.py          # Telegram Bot API integration
│   │
│   └── services/
│       ├── __init__.py
│       └── posting_service.py   # Concurrent fan-out orchestrator (asyncio.gather)
│
├── tests/
│   ├── __init__.py
│   ├── test_validation.py       # Pydantic 200-char, URL, scheme, hostname tests
│   ├── test_platforms.py        # Isolated unit tests for each platform adapter
│   └── test_posting.py          # E2E & concurrency posting service tests
│
├── .env.example                 # Documented template for platform credentials
├── .gitignore                   # Excludes secrets, caches, and shims
├── requirements.txt             # Locked project dependencies
└── README.md                    # Comprehensive documentation
```

---

## 4. Platform Integrations & Documentation References

| Platform | Official API Documentation | Authentication Mechanism | Target Endpoint |
|---|---|---|---|
| **Bluesky** | [docs.bsky.app](https://docs.bsky.app/) | AT Protocol XRPC Session (`accessJwt`) | `com.atproto.repo.createRecord` |
| **Mastodon** | [docs.joinmastodon.org](https://docs.joinmastodon.org/methods/statuses/) | OAuth 2.0 Bearer Token | `POST /api/v1/statuses` |
| **DEV.to** | [developers.forem.com](https://developers.forem.com/api/v1) | API Key (`api-key` header) | `POST /api/articles` |
| **WordPress** | [developer.wordpress.org](https://developer.wordpress.org/rest-api/reference/posts/) | HTTP Basic Auth with Application Password | `POST /wp/v2/posts` |
| **Telegram** | [core.telegram.org/bots/api](https://core.telegram.org/bots/api) | Bot Token (path-based auth) | `POST /bot<token>/sendMessage` |

---

## 5. Getting Started & Installation

### Prerequisites
- Python 3.11 or higher
- Git

### Installation Steps
```bash
# 1. Clone repository
git clone https://github.com/Guptsonu22/DXORA.git
cd DXORA

# 2. Create virtual environment
python -m venv .venv

# 3. Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

### Configuration (.env)
Copy the template and fill in your platform credentials:
```bash
cp .env.example .env
```

---

## 6. Running the Application

Start the FastAPI application on port 4000:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000 --reload
```

Once running:
- **Interactive Swagger Documentation:** [http://localhost:4000/docs](http://localhost:4000/docs)
- **Alternative ReDoc UI:** [http://localhost:4000/redoc](http://localhost:4000/redoc)
- **Health Check Endpoint:** [http://localhost:4000/health](http://localhost:4000/health)
- **Business Posting Endpoint:** `POST http://localhost:4000/posting`

---

## 7. Running the Test Suite

```bash
# Run all tests with verbose output
pytest -v

# Run with coverage report
pytest --cov=app tests/
```

---

## 8. Verification & Integration Status

| Platform | Mocked Wire Tests | Actual Credentials Verified | Notes |
|---|---|---|---|
| **Bluesky** | Verified (`respx`) | Optional via `.env` | Tested session refresh & UTF-8 byte facets |
| **Mastodon** | Verified (`respx`) | Optional via `.env` | Tested permalinks & idempotency keys |
| **DEV.to** | Implemented Phase 6 | Optional via `.env` | Title/body conversion & published=true |
| **WordPress** | Implemented Phase 7 | Optional via `.env` | Application Passwords & status=publish |
| **Telegram** | Implemented Phase 8 | Optional via `.env` | Public vs private channel handling |
