# App Flow Document
## Project: AutoPost Nexus — Automated Multi-Platform Posting System
**Company / Assessment:** Dxora Technologies Python Practical Test  
**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Role:** UX Strategist & Lead Systems Architect  

---

### 1. Overview of System Interfaces
The application provides two unified control surfaces:
1. **The Interactive CLI Surface:** Terminal-first operations for quick publishing, batch operations, system health checks, and scheduled job inspections.
2. **The REST API Surface (Swagger UI / ReDoc):** Programmatic HTTP endpoints with an interactive browser dashboard at `/docs` allowing visual parameter input, execution, and JSON inspection.

---

### 2. End-to-End User Journey Maps

#### Flow A: Immediate Multi-Platform Broadcast
```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant CLI as CLI / REST API
    participant PostService as Post Service
    participant Validator as Content Validator
    participant DB as SQLite / Postgres DB
    participant Dispatcher as Async Dispatcher
    participant Adapters as Platform Adapters
    participant Networks as Third-Party APIs

    User->>CLI: Submit Post(content, title, [twitter, telegram, discord])
    CLI->>PostService: create_and_broadcast()
    PostService->>Validator: validate(content, targets)
    
    alt Validation Failure (e.g. Content > 280 chars for Twitter)
        Validator-->>PostService: Validation Error Details
        PostService-->>CLI: HTTP 422 / CLI Error "Text exceeds Twitter limit"
        CLI-->>User: Display error with character count badge
    else Validation Success
        Validator-->>PostService: Sanitized & Formatted Payloads
        PostService->>DB: INSERT Post (Status: IN_PROGRESS) + Targets (Status: PENDING)
        PostService->>Dispatcher: dispatch_parallel(post_id, targets)
        
        par Dispatch to Twitter
            Dispatcher->>Adapters: TwitterAdapter.publish()
            Adapters->>Networks: POST /2/tweets
            Networks-->>Adapters: 201 Created (id: 18274...)
            Adapters-->>Dispatcher: PublishSuccess(id, url)
            Dispatcher->>DB: UPDATE Target SET Status=SUCCESS
        and Dispatch to Telegram
            Dispatcher->>Adapters: TelegramAdapter.publish()
            Adapters->>Networks: POST /sendMessage
            Networks-->>Adapters: 200 OK (message_id: 994)
            Adapters-->>Dispatcher: PublishSuccess(id, url)
            Dispatcher->>DB: UPDATE Target SET Status=SUCCESS
        and Dispatch to Discord
            Dispatcher->>Adapters: DiscordAdapter.publish()
            Adapters->>Networks: POST /webhooks/...
            Networks-->>Adapters: 204 No Content
            Adapters-->>Dispatcher: PublishSuccess()
            Dispatcher->>DB: UPDATE Target SET Status=SUCCESS
        end
        
        Dispatcher->>DB: UPDATE Post SET Status=COMPLETED
        Dispatcher-->>PostService: Broadcast Summary
        PostService-->>CLI: Return Full Post Object with Target IDs & URLs
        CLI-->>User: Render Rich Success Table with live URLs
    end
```

---

#### Flow B: Handling Partial Failure & Selective Retry
```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant CLI as CLI / REST API
    participant PostService as Post Service
    participant DB as Database
    participant Dispatcher as Async Dispatcher
    participant Adapters as Platform Adapters

    Note over User,Adapters: Initial broadcast where LinkedIn token had expired (HTTP 401)
    Dispatcher->>DB: Target[Twitter] = SUCCESS
    Dispatcher->>DB: Target[LinkedIn] = FAILED (Error: "HTTP 401 Unauthorized")
    Dispatcher->>DB: Post = PARTIALLY_FAILED
    
    User->>CLI: Check Status (post_id)
    CLI->>DB: Fetch Post & Targets
    CLI-->>User: Show Summary: Twitter: SUCCESS, LinkedIn: FAILED
    
    Note over User: User updates LINKEDIN_ACCESS_TOKEN in .env
    User->>CLI: Trigger Retry(post_id)
    CLI->>PostService: retry_failed_targets(post_id)
    PostService->>DB: Query targets WHERE post_id=:id AND status='FAILED'
    DB-->>PostService: [LinkedIn Target]
    
    Note over PostService,Dispatcher: Only LinkedIn is scheduled for execution! Twitter is skipped.
    PostService->>Dispatcher: dispatch_parallel(post_id, [LinkedIn])
    Dispatcher->>Adapters: LinkedInAdapter.publish()
    Adapters-->>Dispatcher: PublishSuccess(urn:li:share:12345)
    Dispatcher->>DB: UPDATE Target[LinkedIn] SET Status=SUCCESS
    Dispatcher->>DB: UPDATE Post SET Status=COMPLETED
    
    PostService-->>CLI: Updated Post Details
    CLI-->>User: Display Success: All platforms now COMPLETED!
```

---

#### Flow C: Scheduled Post Lifecycle
```mermaid
stateDiagram-v2
    [*] --> DRAFT : Create Draft
    DRAFT --> SCHEDULED : Submit with scheduled_at
    SCHEDULED --> CANCELLED : User Cancels before trigger
    SCHEDULED --> IN_PROGRESS : APScheduler triggers at target time
    IN_PROGRESS --> COMPLETED : All targets publish with 200/201
    IN_PROGRESS --> PARTIALLY_FAILED : 1 or more targets fail permanently
    IN_PROGRESS --> FAILED : All targets fail permanently
    PARTIALLY_FAILED --> RETRYING : User/System triggers selective retry
    FAILED --> RETRYING : User/System triggers selective retry
    RETRYING --> COMPLETED : Retried targets succeed
    RETRYING --> PARTIALLY_FAILED : Some targets still fail
    COMPLETED --> [*]
    CANCELLED --> [*]
```

---

### 3. Screen, Route & Command Specifications

#### 3.1 REST API Routes (Swagger UI at `/docs`)
| Method | Route | Description | Success Response | Error Responses |
|---|---|---|---|---|
| `POST` | `/api/v1/posts` | Create and immediately publish or schedule a post. | `201 Created` with Post Schema | `400 Bad Request`, `422 Unprocessable Entity` |
| `GET` | `/api/v1/posts` | List posts with pagination, status filter, and platform filter. | `200 OK` (list of posts + total count) | `400 Bad Request` |
| `GET` | `/api/v1/posts/{id}` | Retrieve comprehensive post status, target breakdowns, and logs. | `200 OK` (detailed post object) | `404 Not Found` |
| `POST` | `/api/v1/posts/{id}/retry`| Re-attempt execution *only* for failed targets. | `200 OK` (updated post object) | `404 Not Found`, `400 No Failed Targets` |
| `DELETE` | `/api/v1/posts/{id}` | Cancel a scheduled post or delete a draft. | `200 OK` (cancellation confirmed) | `404 Not Found`, `400 Cannot Cancel Completed Post` |
| `GET` | `/api/v1/health` | Diagnostic connectivity check for all configured platform APIs. | `200 OK` (per-platform latency & status) | `503 Service Unavailable` (if critical dependencies down) |

#### 3.2 CLI Commands
- `python -m autopost_nexus.cli post "Content here" --platforms twitter,telegram,discord`
  - Action: Immediate validation and broadcast.
  - Success State: Colored table listing Platform, Status (`SUCCESS`), Post ID, and Direct Post URL.
  - Failure State: Colored table showing which platforms succeeded and exact error message for failed ones.
- `python -m autopost_nexus.cli schedule "Content here" --at "2026-11-20T10:00:00" --platforms linkedin,telegram`
  - Action: Registers post in database and schedules job with APScheduler.
  - State: Displays Scheduled confirmation with Job ID and countdown.
- `python -m autopost_nexus.cli list --limit 10`
  - Action: Renders recent posts, scheduled jobs, and statuses.
  - Empty State: "No posts found in database. Create your first post using `autopost_nexus.cli post`."
- `python -m autopost_nexus.cli retry <post_id>`
  - Action: Selectively replays only the failed target platforms for that post ID.
- `python -m autopost_nexus.cli health`
  - Action: Pings and authenticates with all configured external platform APIs.
  - Output: Diagnostic matrix: Platform Name, Configured (Yes/No), Auth Test (PASS/FAIL), Latency (ms).

---

### 4. Edge Cases & Error States
1. **Network Timeout:** Handled by HTTP client timeout (default 10s), logged as `TIMEOUT`, retried up to 3 times with exponential backoff before transitioning to `FAILED`.
2. **HTTP 429 Rate Limit:** System checks for `Retry-After` header. If <= 60 seconds, it pauses and retries; if > 60 seconds, it marks target as `FAILED (Rate Limit Exceeded: Retry After X s)` to avoid blocking the worker thread.
3. **Invalid File Format / Large Media:** Handled immediately in the pre-flight validation phase before any API call is initiated, returning clean actionable feedback.
4. **Duplicate Submission:** Idempotency manager returns existing post record with HTTP 200 and a header `X-Idempotent-Replay: true`.
