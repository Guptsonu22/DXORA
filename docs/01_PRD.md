# Product Requirements Document (PRD)
## Project: AutoPost Nexus — Automated Multi-Platform Posting System
**Company / Assessment:** Dxora Technologies Python Practical Test  
**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Role:** Senior Product Manager & Senior Software Architect  

---

### 1. App Overview & Executive Summary
**AutoPost Nexus** is a robust, modular, and resilient backend multi-platform posting engine designed to automate the authoring, formatting, scheduling, and distribution of rich content across diverse social media, messaging, and community channels. 

The system provides a unified abstraction over distinct third-party APIs (X/Twitter, LinkedIn, Telegram, Discord, Reddit), decoupling content authoring from platform-specific technical constraints (such as character limits, media upload workflows, rate limits, and authentication formats).

---

### 2. One-Line App Idea
> A unified, resilient Python-based content distribution engine that validates, schedules, and broadcasts multimedia posts across multiple platforms with granular per-platform failure isolation, automatic retries, and audit logging.

---

### 3. Target Users & Personas
1. **Developer Advocates & Growth Engineers:** Automate release notes, changelogs, and announcements simultaneously across Discord, Telegram, Twitter, and LinkedIn.
2. **Social Media Managers & Content Operations:** Schedule campaign posts weeks in advance with guaranteed delivery and selective retry on platform failure.
3. **Internal Systems & Alert Bots:** Programmatic microservice integration via REST API to broadcast urgent operational notices or marketing broadcasts.

---

### 4. Problem Statement & Key Challenges
1. **API Fragmentation:** Every platform uses a different protocol, auth scheme (OAuth 1.0a, OAuth 2.0 Bearer, Bot Tokens, Webhook URLs), and media ingestion process.
2. **Platform Constraints & Mismatches:**
   - Twitter restricts free text to 280 characters.
   - LinkedIn allows 3,000 characters and supports rich article formatting.
   - Telegram supports 4,096 characters with HTML/Markdown parsing modes.
   - Discord channels accept 2,000 characters with rich embeds.
   - Reddit requires subreddit naming, link vs. self-post typing, and title-body separation.
3. **The "All-or-Nothing" Broadcast Failure Antipattern:**
   In naive implementations, if broadcasting to 4 platforms and the 3rd platform fails due to a rate limit or network glitch, the whole transaction fails or leaves the system in an unknown state, risking duplicate cross-posts.
4. **Lack of Verifiable Observability:**
   Lack of wire-level audit trails and telemetry makes debugging API integration issues tedious and error-prone.

---

### 5. Core Features
- **Multi-Platform Dispatcher:** Broadcast single content payload simultaneously to multiple target platforms with a single command or API call.
- **Intelligent Content Validation & Sanitizer Pipeline:** Pre-flight checks on character count, media dimensions/formats, and required metadata per platform before any network call is dispatched.
- **Granular Target-Level State Machine:** Each target platform in a broadcast maintains an independent status (`PENDING`, `SUCCESS`, `FAILED`, `RETRYING`).
- **Resilience Engine:**
  - Automatic exponential backoff with jitter on transient network failures and HTTP 429 (Rate Limit) responses.
  - Idempotency key tracking to guarantee zero duplicate posts.
  - Selective retry mechanism: re-run *only* the failed targets without re-posting to platforms that already succeeded.
- **Scheduling Engine:** Date-based and cron-based scheduling using persistent job storage and missed-job recovery.
- **Media Asset Management:** Handle single/multi-image attachments with metadata validation and per-platform chunked/direct upload flows.
- **Dual Presentation Interfaces:**
  - **REST API:** FastAPI application with comprehensive OpenAPI/Swagger documentation at `/docs`.
  - **Interactive CLI:** Typer-powered terminal interface with Rich styling, tables, progress indicators, and health diagnostics.
- **Platform Health & Connectivity Diagnostics:** Probe endpoint verifying API key validity, latency, and quota health for each integrated platform.

---

### 6. User Roles & Permissions
- **System Administrator:** Configures global platform credentials, monitors background workers, inspects audit logs, and triggers system-wide health checks.
- **Publisher / Content Author:** Submits new posts, schedules future broadcasts, views post delivery statuses, and triggers retries on failed channels.

---

### 7. User Stories
- **US-01 (Unified Composition):** As a Content Creator, I want to write a post once and specify `[twitter, linkedin, telegram, discord]` as targets so that I don't have to copy-paste across separate browser tabs.
- **US-02 (Pre-flight Validation):** As a Creator, I want immediate validation if my post exceeds Twitter's 280 characters, so I can adjust the text or choose thread generation before broadcasting.
- **US-03 (Fault Isolation):** As an Admin, if LinkedIn returns HTTP 401 (token expired) during a broadcast, I want Telegram and Discord to still publish successfully, and the system to mark LinkedIn as `FAILED` with the exact error message.
- **US-04 (Selective Retry):** As an Admin, after refreshing the LinkedIn token, I want to trigger a retry for that specific post so that LinkedIn is published without sending duplicate posts to Telegram and Discord.
- **US-05 (Scheduled Publishing):** As a Marketer, I want to schedule a post for a product launch at 09:00 AM UTC tomorrow, and have the system execute the dispatch reliably in the background.
- **US-06 (Live Diagnostics):** As an Engineer, I want to run a `health` check command from the CLI to verify which platform APIs are connected and functional before initiating a campaign.

---

### 8. Success Metrics & Key Performance Indicators (KPIs)
| Metric | Target | Verification Method |
|---|---|---|
| **Posting Reliability** | 99.9% delivery of valid posts | Automated integration test suite |
| **Duplicate Rate** | 0.00% duplicates on retries | Idempotency key unit & load tests |
| **Fault Isolation** | 100% independent target status | Mocked partial failure test scenario |
| **API Latency (Dispatch)**| < 250ms for asynchronous ingestion | Endpoint benchmark tests |
| **Test Coverage** | > 90% statement & branch coverage | `pytest-cov` report |

---

### 9. MVP Scope (Version 1.0)
- Core Adapters: **X / Twitter v2**, **LinkedIn v2**, **Telegram Bot**, **Discord Webhook/Bot**, **Reddit API**.
- Database: Async SQLAlchemy 2.0 with SQLite (zero external dependencies) and Postgres-ready connection pooling.
- Application Layer: FastAPI REST API + Swagger UI + Redoc.
- CLI Layer: Typer CLI with Rich terminal tables.
- Scheduling: Persistent APScheduler with background worker.
- Resiliency: Idempotency keys + exponential backoff retry + selective retry.
- Testing: Hermetic WireMock testbed using `respx` covering 200, 400, 401, 429, 500, 503 HTTP responses.

---

### 10. Out of Scope for Version 1.0 (Future Roadmap)
- Video transcoding & chunked slicing for 4K video.
- Multi-tenant enterprise RBAC with OAuth login portals.
- Automated AI-assisted copywriting (modular hook provided for future plug-in).
