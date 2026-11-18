# AutoPost Nexus — Evidence & Screenshot Collection Guide
**Dxora Technologies Practical Assessment — Part 12 Evidence Collection**

This guide provides exact steps and commands for capturing all 6 required verification screenshots for submission.

---

## Screenshot 1: Swagger UI & API Success
- **Target URL:** `http://localhost:4000/docs`
- **Objective:** Demonstrate the interactive Swagger UI and successful multi-platform broadcast execution.
- **Steps to Reproduce:**
  1. Start the server:
     ```bash
     python run.py
     # Or: uvicorn app.main:app --host 0.0.0.0 --port 4000
     ```
  2. Open browser to `http://localhost:4000/docs`.
  3. Expand `POST /posting` under **Business Posting Endpoint**.
  4. Click **Try it out**.
  5. In the request body, enter:
     ```json
     {
       "message": "Check out our latest business platform and grow your online visibility. https://example.com"
     }
     ```
  6. Click **Execute**.
  7. Verify Response Code **200 OK** and response body containing all 5 platforms.
  8. **Capture Screenshot:** Take full-window screenshot showing Swagger UI, request body, and 200 OK response.
  9. **Save As:** `evidence/screenshots/01_swagger_success.png`

---

## Screenshot 2: Validation Error Gate (HTTP 422)
- **Target URL:** `http://localhost:4000/docs`
- **Objective:** Demonstrate strict input validation rejecting invalid payloads per Part 4.
- **Steps to Reproduce:**
  1. In Swagger UI on `POST /posting`, submit an invalid payload:
     ```json
     {
       "message": "This message is invalid because it is missing a CTA link."
     }
     ```
  2. Click **Execute**.
  3. Verify Response Code **422 Unprocessable Entity** with validation error detail:
     `"Message must contain exactly one CTA URL (HTTP or HTTPS). None found."`
  4. Also test submitting extra forbidden fields:
     ```json
     {
       "message": "Valid text https://example.com",
       "platforms": ["twitter"]
     }
     ```
  5. Verify Response Code **422 Unprocessable Entity** with:
     `"Extra inputs are not permitted"` on `platforms`.
  6. **Capture Screenshot:** Capture the 422 error response in Swagger UI.
  7. **Save As:** `evidence/screenshots/02_validation_error.png`

---

## Screenshot 3: Multi-Platform Posting Aggregated Response
- **Objective:** Show the complete JSON payload showing all 5 platforms with standardized fields per Part 6 & Part 7.
- **Curl Command:**
  ```bash
  curl -X POST http://localhost:4000/posting \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"Check out our latest platform https://example.com\"}"
  ```
- **Key Details to Highlight:**
  - `success: true`
  - `total_platforms: 5`
  - `successful: 5` (or partial)
  - `results`: List with `platform`, `status`, `posted_url`, `public_access`, `date`, `time`, `error`.
- **Capture Screenshot:** Terminal or Postman/Insomnia window displaying formatted JSON response.
- **Save As:** `evidence/screenshots/03_aggregated_response.png`

---

## Screenshot 4: Independent Platform Failure & Fault Isolation
- **Objective:** Demonstrate that one platform failing or unconfigured does not crash the system or stop other platforms.
- **Steps to Reproduce:**
  1. Ensure at least one platform is unconfigured or has invalid credentials in `.env` (e.g. invalid `MASTODON_ACCESS_TOKEN`).
  2. Submit post:
     ```bash
     curl -X POST http://localhost:4000/posting \
       -H "Content-Type: application/json" \
       -d "{\"message\": \"Fault isolation test https://example.com\"}"
     ```
  3. Response will show:
     - `success: true`
     - Failing platform has `status: "failed"` and detailed error string.
     - Successful platforms have `status: "success"`, permalinks, and timestamps.
- **Capture Screenshot:** Response showing mixed success and failed statuses side-by-side.
- **Save As:** `evidence/screenshots/04_fault_isolation.png`

---

## Screenshot 5: Actual Platform Publication Evidence (Optional Live Mode)
- **Objective:** Display real third-party publication post permalink in a browser or live channel.
- **Live Channels Verified:**
  - Telegram Public Channel: Direct view of posted message in `https://t.me/<channel_name>/<msg_id>`.
  - Bluesky: Post view on `https://bsky.app/profile/<handle>/post/<rkey>`.
  - Mastodon: Status view on `https://<instance>/@<user>/<status_id>`.
  - DEV.to: Live article on `https://dev.to/<username>/<slug>`.
  - WordPress: Live published blog post on `https://<site>/<year>/<month>/<slug>/`.
- **Capture Screenshot:** Browser tab showing the published post on the live platform.
- **Save As:** `evidence/screenshots/05_actual_platform_publication.png`

---

## Screenshot 6: Pytest Complete Test Suite Results
- **Objective:** Demonstrate 100% test pass rate across the full automated test suite.
- **Command:**
  ```bash
  pytest -v
  ```
- **Key Details to Highlight:**
  - `181 passed, 5 skipped in ~20s`
  - Zero test failures (`100% pass rate`)
  - All test files listed (`test_validation.py`, `test_platforms.py`, `test_central_posting_service.py`, `test_startup_and_swagger.py`, etc.)
- **Capture Screenshot:** Full terminal output showing test session start, passing green tests, and summary footer.
- **Save As:** `evidence/screenshots/06_pytest_terminal_results.png`
