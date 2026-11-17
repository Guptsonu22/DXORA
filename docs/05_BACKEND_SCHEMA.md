# Backend Schema Document
## Project: AutoPost Nexus — Automated Multi-Platform Posting System
**Company / Assessment:** Dxora Technologies Python Practical Test  
**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Role:** Senior Backend Engineer & Database Architect  

---

### 1. Database Architecture & Engine Overview
AutoPost Nexus is architected around **SQLAlchemy 2.0 (AsyncIO)**.
- **Default Local Engine:** SQLite with `aiosqlite` (`sqlite+aiosqlite:///autopost_nexus.db`). Enables zero external server dependencies, immediate offline development, and 100% reproducible test suites.
- **Production Engine:** PostgreSQL with `asyncpg` (`postgresql+asyncpg://user:pass@host/dbname`). The schema is strictly compliant with standard ANSI SQL data types, making dialect switching seamless by merely setting `DATABASE_URL`.
- **Concurrency & Locking:** Foreign key enforcement (`PRAGMA foreign_keys=ON` for SQLite) and connection pooling with statement timeouts.

---

### 2. Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    POST ||--o{ POST_TARGET : "fans out to"
    POST ||--o{ MEDIA_ASSET : "attaches"
    POST_TARGET ||--o{ PUBLISH_AUDIT_LOG : "records execution"

    POST {
        VARCHAR_36 id PK "UUID string"
        VARCHAR_255 title "Post title / headline"
        TEXT content "Body text content"
        VARCHAR_32 status "DRAFT, SCHEDULED, IN_PROGRESS, COMPLETED, PARTIALLY_FAILED, FAILED"
        VARCHAR_64 idempotency_key UK "Unique deduplication hash"
        DATETIME scheduled_at "Optional scheduled dispatch timestamp"
        DATETIME created_at "Creation timestamp UTC"
        DATETIME updated_at "Update timestamp UTC"
    }

    POST_TARGET {
        VARCHAR_36 id PK "UUID string"
        VARCHAR_36 post_id FK "Reference to POST.id"
        VARCHAR_32 platform "TWITTER, LINKEDIN, TELEGRAM, DISCORD, REDDIT"
        VARCHAR_32 status "PENDING, PUBLISHING, SUCCESS, FAILED, RETRYING"
        VARCHAR_255 external_post_id "Remote platform ID"
        TEXT external_url "Direct public URL to post"
        INTEGER retry_count "Number of retry attempts executed"
        TEXT error_message "Failure reason or HTTP error"
        DATETIME published_at "Timestamp of successful broadcast"
        DATETIME created_at "Creation timestamp UTC"
        DATETIME updated_at "Update timestamp UTC"
    }

    MEDIA_ASSET {
        VARCHAR_36 id PK "UUID string"
        VARCHAR_36 post_id FK "Reference to POST.id"
        TEXT file_path "Local filesystem or cloud URL path"
        VARCHAR_64 mime_type "image/png, image/jpeg, etc."
        BIGINT file_size_bytes "Size in bytes"
        VARCHAR_255 alt_text "Accessibility alt text"
        DATETIME created_at "Creation timestamp UTC"
    }

    PUBLISH_AUDIT_LOG {
        VARCHAR_36 id PK "UUID string"
        VARCHAR_36 target_id FK "Reference to POST_TARGET.id"
        VARCHAR_32 event_type "ATTEMPT, SUCCESS, RETRY_BACKOFF, RATE_LIMITED, FAILURE"
        INTEGER http_status_code "HTTP status code from remote API"
        TEXT request_headers_masked "Masked outbound headers"
        TEXT response_body_snippet "Truncated remote response body"
        INTEGER execution_latency_ms "Round-trip latency in ms"
        DATETIME timestamp "Execution timestamp UTC"
    }
```

---

### 3. Detailed Table Specifications

#### 3.1 `posts`
Represents the authored piece of content prior to or during distribution.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | RFC 4122 UUID v4 |
| `title` | `VARCHAR(255)` | NULLABLE | Optional post title (mandatory for Reddit, used as header elsewhere) |
| `content` | `TEXT` | NOT NULL | Canonical content text |
| `status` | `VARCHAR(32)` | NOT NULL, DEFAULT 'DRAFT' | State machine enum |
| `idempotency_key` | `VARCHAR(64)` | UNIQUE, NULLABLE | SHA-256 hash or client-provided UUID |
| `scheduled_at` | `DATETIME` | NULLABLE | Execution timestamp in UTC |
| `created_at` | `DATETIME` | NOT NULL, DEFAULT UTC_NOW | Timestamp of record creation |
| `updated_at` | `DATETIME` | NOT NULL, DEFAULT UTC_NOW | Timestamp of last modification |

**Indexes:**
- `ix_posts_status` ON (`status`)
- `ix_posts_scheduled_at` ON (`scheduled_at`)
- `ix_posts_idempotency_key` ON (`idempotency_key`) UNIQUE

---

#### 3.2 `post_targets`
Represents the target platform-specific slice of the broadcast. Critical for partial failure isolation.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | RFC 4122 UUID v4 |
| `post_id` | `VARCHAR(36)` | FOREIGN KEY (`posts.id` ON DELETE CASCADE), NOT NULL | Parent post reference |
| `platform` | `VARCHAR(32)` | NOT NULL | Enum: `TWITTER`, `LINKEDIN`, `TELEGRAM`, `DISCORD`, `REDDIT` |
| `status` | `VARCHAR(32)` | NOT NULL, DEFAULT 'PENDING' | Enum: `PENDING`, `PUBLISHING`, `SUCCESS`, `FAILED`, `RETRYING` |
| `external_post_id` | `VARCHAR(255)` | NULLABLE | Remote ID returned by platform (e.g. tweet ID, post URN) |
| `external_url` | `TEXT` | NULLABLE | Public direct URL to post |
| `retry_count` | `INTEGER` | NOT NULL, DEFAULT 0 | Count of retry attempts |
| `error_message` | `TEXT` | NULLABLE | Last error message if failed |
| `published_at` | `DATETIME` | NULLABLE | Successful publication timestamp |
| `created_at` | `DATETIME` | NOT NULL, DEFAULT UTC_NOW | Creation timestamp |
| `updated_at` | `DATETIME` | NOT NULL, DEFAULT UTC_NOW | Modification timestamp |

**Indexes & Constraints:**
- `uq_post_platform` UNIQUE (`post_id`, `platform`) — Prevents duplicate dispatch to the same platform for one post.
- `ix_post_targets_status` ON (`status`)
- `ix_post_targets_platform` ON (`platform`)

---

#### 3.3 `media_assets`
Represents multimedia attachments associated with a post.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | RFC 4122 UUID v4 |
| `post_id` | `VARCHAR(36)` | FOREIGN KEY (`posts.id` ON DELETE CASCADE), NOT NULL | Parent post reference |
| `file_path` | `TEXT` | NOT NULL | Local path or remote CDN URL |
| `mime_type` | `VARCHAR(64)` | NOT NULL | e.g. `image/jpeg`, `image/png`, `image/gif` |
| `file_size_bytes` | `BIGINT` | NOT NULL | Size of media in bytes |
| `alt_text` | `VARCHAR(255)` | NULLABLE | Accessibility description |
| `created_at` | `DATETIME` | NOT NULL, DEFAULT UTC_NOW | Creation timestamp |

---

#### 3.4 `publish_audit_logs`
Provides complete, immutable audit telemetry for compliance, debugging, and postmortems.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | RFC 4122 UUID v4 |
| `target_id` | `VARCHAR(36)` | FOREIGN KEY (`post_targets.id` ON DELETE CASCADE), NOT NULL | Target reference |
| `event_type` | `VARCHAR(32)` | NOT NULL | Enum: `ATTEMPT`, `SUCCESS`, `RETRY_BACKOFF`, `RATE_LIMITED`, `FAILURE` |
| `http_status_code` | `INTEGER` | NULLABLE | Remote HTTP response code (200, 429, etc.) |
| `request_headers_masked` | `TEXT` | NULLABLE | Outbound headers with sensitive tokens redacted |
| `response_body_snippet` | `TEXT` | NULLABLE | Safe snippet of response (up to 1KB) |
| `execution_latency_ms` | `INTEGER` | NULLABLE | Time taken in milliseconds |
| `timestamp` | `DATETIME` | NOT NULL, DEFAULT UTC_NOW | Event log timestamp |

---

### 4. State Machine Transition Rules

```text
Post Lifecycle:
[DRAFT] -> [SCHEDULED] (if scheduled_at is in the future)
[DRAFT] -> [IN_PROGRESS] (if immediate broadcast triggered)
[SCHEDULED] -> [IN_PROGRESS] (when scheduler timer fires)
[IN_PROGRESS] -> [COMPLETED] (when ALL targets have status == SUCCESS)
[IN_PROGRESS] -> [PARTIALLY_FAILED] (when at least 1 target == SUCCESS and >= 1 target == FAILED)
[IN_PROGRESS] -> [FAILED] (when ALL targets have status == FAILED)
[PARTIALLY_FAILED / FAILED] -> [RETRYING] (when selective retry is triggered)
[RETRYING] -> [COMPLETED / PARTIALLY_FAILED / FAILED] (based on retry outcomes)
```
