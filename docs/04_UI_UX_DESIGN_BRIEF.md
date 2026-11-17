# UI/UX Design Brief
## Project: AutoPost Nexus — Automated Multi-Platform Posting System
**Company / Assessment:** Dxora Technologies Python Practical Test  
**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Role:** Senior UI/UX Designer & Frontend Architect  

---

### 1. Design Philosophy & Aesthetic Identity
**AutoPost Nexus** embodies a modern, developer-centric, and high-clarity technical aesthetic. Whether interacting through the interactive terminal (CLI) or the browser-based API/Web interface, the user experience must evoke speed, precision, rock-solid reliability, and zero ambiguity.

Key Design Tenets:
- **Instant Visual Feedback:** Operations provide immediate status cues (Spinners, Progress bars, Color-coded badges).
- **Graceful Degradation & High Information Density:** Complex multi-platform broadcasts present aggregate health first, expandable to wire-level diagnostic logs.
- **Defensive Error Highlighting:** Errors are not just stack traces; they are highlighted with actionable remediation guidance (e.g., exact character counts over limit, missing credential names).

---

### 2. Design Tokens & Color Palette

#### 2.1 Core Palette (Terminal & Web Dashboard)
- **Primary / Accent (Cyan / Electric Blue):** `#00D2FF` / ANSI Cyan — represents active operations, headers, command prefixes.
- **Success (Emerald Green):** `#10B981` / ANSI Bright Green — indicates `200/201 SUCCESS`, healthy platforms, completed broadcasts.
- **Warning / Retrying (Amber Gold):** `#F59E0B` / ANSI Yellow — indicates rate limit backoff, retrying state, near character limit.
- **Failure / Error (Crimson Red):** `#EF4444` / ANSI Bright Red — indicates rejected validation, auth failure, `FAILED` target status.
- **Neutral Dark / Background:** `#0F172A` (Slate 900) — dark mode background for console and dashboard.
- **Neutral Light / Foreground:** `#F8FAFC` (Slate 50) — clean readable body text.
- **Muted / Subtext:** `#64748B` (Slate 500) — timestamps, UUIDs, debug telemetry.

---

### 3. Interactive CLI UX Specification (Powered by `Rich`)

#### 3.1 Broadcast Output Mockup (Success Scenario)
```text
╭────────────────── AutoPost Nexus — Multi-Platform Broadcast ──────────────────╮
│ Post ID: 550e8400-e29b-41d4-a716-446655440000                                 │
│ Title: Launching AutoPost Nexus v1.0                                          │
│ Content: "Excited to introduce AutoPost Nexus! Real-time cross-posting... 🚀" │
╰────────────────────────────────────────────────────────────────────────────────╯

⠋ Dispatching concurrent broadcast across 4 platforms...
✔ Twitter/X       [SUCCESS]  ID: 178239014  URL: https://x.com/user/status/178239014
✔ LinkedIn        [SUCCESS]  ID: urn:li:19  URL: https://linkedin.com/feed/update/urn:li:19
✔ Telegram        [SUCCESS]  ID: msg:4891   URL: https://t.me/c/12345/4891
✔ Discord         [SUCCESS]  ID: dsc:8821   Channel: #announcements

┌──────────┬───────────┬──────────────┬──────────────────────────────────────────┐
│ Platform │ Status    │ Attempts     │ Remote URL / Target Reference            │
├──────────┼───────────┼──────────────┼──────────────────────────────────────────┤
│ Twitter  │ ● SUCCESS │ 1            │ https://x.com/user/status/178239014      │
│ LinkedIn │ ● SUCCESS │ 1            │ https://linkedin.com/feed/update/urn:li: │
│ Telegram │ ● SUCCESS │ 1            │ https://t.me/c/12345/4891                │
│ Discord  │ ● SUCCESS │ 1            │ Channel: #announcements                  │
└──────────┴───────────┴──────────────┴──────────────────────────────────────────┘
Broadcast completed in 412ms (100% success rate).
```

#### 3.2 Broadcast Output Mockup (Partial Failure Scenario)
```text
┌──────────┬───────────┬──────────────┬──────────────────────────────────────────┐
│ Platform │ Status    │ Attempts     │ Remote URL / Error Details               │
├──────────┼───────────┼──────────────┼──────────────────────────────────────────┤
│ Twitter  │ ● SUCCESS │ 1            │ https://x.com/user/status/178239014      │
│ LinkedIn │ ✖ FAILED  │ 3 (exhausted)│ HTTP 401: Invalid or expired Bearer Token│
│ Telegram │ ● SUCCESS │ 1            │ https://t.me/c/12345/4891                │
│ Discord  │ ● SUCCESS │ 1            │ Channel: #announcements                  │
└──────────┴───────────┴──────────────┴──────────────────────────────────────────┘
⚠ Notice: Post status is PARTIALLY_FAILED.
To retry failed targets after fixing credentials, run:
$ python -m autopost_nexus.cli retry 550e8400-e29b-41d4-a716-446655440000
```

#### 3.3 Platform Health Matrix (`autopost_nexus.cli health`)
```text
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                  Platform Connectivity & Health Diagnostic             ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┌──────────┬────────────┬─────────────┬──────────────┬───────────────────┐
│ Platform │ Configured │ Auth Status │ Latency (ms) │ Details / Quota   │
├──────────┼────────────┼─────────────┼──────────────┼───────────────────┤
│ Twitter  │ Configured │ ✔ VERIFIED  │ 128ms        │ OAuth 1.0a Valid  │
│ LinkedIn │ Configured │ ✔ VERIFIED  │ 210ms        │ Token expires 60d │
│ Telegram │ Configured │ ✔ VERIFIED  │ 84ms         │ Bot: @NexusPostBot│
│ Discord  │ Configured │ ✔ VERIFIED  │ 92ms         │ Webhook Active    │
│ Reddit   │ Not Config │ ○ DISABLED  │ —            │ Keys omitted      │
└──────────┴────────────┴─────────────┴──────────────┴───────────────────┘
```

---

### 4. REST API Swagger / OpenAPI Design Direction
- Custom FastAPI theme with Dark Mode header, Dxora Technologies branding, and structured tag groupings:
  - `🏷 Posts & Broadcasts`: Primary endpoints for creating, scheduling, fetching, and retrying posts.
  - `🏷 Validation`: Pre-flight content and media inspection.
  - `🏷 Platform Health & Diagnostics`: Real-time third-party API connectivity tests.
  - `🏷 Scheduled Queue`: Management of pending and recurring broadcast triggers.
- Rich parameter descriptions, concrete JSON example payloads, and clear HTTP error code specifications for every endpoint.

---

### 5. Accessibility & UX Quality Criteria
1. **WCAG 2.1 AA Compliance:** High color contrast ratio (> 4.5:1) for all terminal text and dashboard elements.
2. **Terminal Independence:** ANSI color codes automatically stripped when piping output or when `NO_COLOR=1` is detected.
3. **Progress Indicators:** Any network call lasting longer than 150ms displays an animated Rich spinner so the operator knows the system is awaiting remote API responses.
