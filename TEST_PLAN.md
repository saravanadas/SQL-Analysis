# UnifiedDataMCP — Complete Test Plan

## Philosophy: Local First, Then Cloud

| Phase | Purpose | What It Catches |
|-------|---------|-----------------|
| **1. Local Smoke** | Verify the app starts and all endpoints respond | Code bugs, import errors, routing problems, FastAPI config |
| **2. Security & Adversarial** | Verify authentication, input validation, and stability | Auth bypass, SQL injection surface, token tampering, concurrency |
| **3. GitHub Actions CI** | Validate Docker build in a clean environment | Missing OS packages, broken Dockerfile, dependency conflicts |
| **4. Railway Production** | Validate real networking, DB connectivity, and cloud secrets | Firewall rules, credential configuration, production-only failures |

**Principle:** Never deploy to production until Phase 1 and Phase 2 pass locally.

---

## Phase 1: Local Smoke Tests (Developer Machine)

**Goal:** Verify the app starts, endpoints respond, and code logic is correct.

**Prerequisites:**
- Docker installed (recommended) OR Python 3.11+ with a virtual environment
- `.env` file configured with real credentials (see Environment Variables Reference below)
- `API_TOKEN` set in `.env` or as an environment variable

### Server Startup

**Option A — Docker (recommended):**
```bash
cd SQL-Analysis
docker build -t unified-mcp .
docker run -p 8000:8000 --env-file .env unified-mcp
```

**Option B — Local Python (development):**
```bash
cd SQL-Analysis
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Startup Gate:** Logs must show:
```
MCP tools registered successfully
MCP mounted successfully at /mcp
Scheduler started
Application startup complete.
```

### Automated Test Runner (Recommended)

The `tests/cli_tests.py` smoke suite covers 13 steps automatically. This is the fastest way to validate the server.

```bash
# Set token and run
$env:API_TOKEN = "your-api-token"                     # PowerShell
export API_TOKEN="your-api-token"                      # Bash

python tests/cli_tests.py

# Override target server
python tests/cli_tests.py --base-url http://localhost:8000 --api-token mytoken

# Stop on first failure
python tests/cli_tests.py --stop-on-failure

# Run via pytest (wraps the suite in a single test function)
pytest tests/cli_tests.py -v
```

**Environment variables for the runner:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `BASE_URL` | `http://localhost:8000` | Server URL |
| `API_TOKEN` | (none) | Bearer token for auth-protected endpoints |
| `JOB_POLL_MAX_RETRIES` | `24` | Max polling attempts for async jobs |
| `JOB_POLL_INTERVAL` | `5` | Seconds between poll attempts |

### Automated Test Steps (cli_tests.py)

The runner executes these 13 steps in order. Steps 6–8 are chained (extract → poll → download). Steps 11–12 are chained (async load → poll).

| Step | Function | Endpoint | Auth | Pass Criteria |
|------|----------|----------|------|---------------|
| 01 | `test_health()` | `GET /health` | No | `{"status":"ok"}` |
| 02 | `test_debug_tools()` | `GET /debug/tools` | Bearer | `tool_count` present; tools include `extract_analytical_to_csv` and `stage_sql_to_railway_async` |
| 03 | `test_debug_tcp()` | `GET /debug/tcp` | Bearer | `{"ok": true}` with `resolved_addresses` |
| 04 | `test_debug_odbc()` | `GET /debug/odbc` | Bearer | `{"ok": true, "server": "..."}` |
| 05 | `test_debug_sql()` | `GET /debug/sql` | Bearer | `{"ok": true, "value": 1}` |
| 06 | `test_extract_sql()` | `POST /extract/sql` | Bearer | Returns `{"job_id": "...", "status": "started"}` |
| 07 | `poll_job()` | `GET /job/{job_id}` | No | Job reaches `status: "completed"` or `"success"` within poll window |
| 08 | `test_download()` | `GET /download/{file_id}?token=...` | HMAC token | HTTP 200 with CSV content |
| 09 | `test_sharepoint_auth()` | `GET /test-sharepoint` | Bearer | `{"status": "success"}` |
| 10 | `test_load_to_railway()` | `POST /load-to-railway` | Bearer | `{"status": "success", "rows_loaded": N}` (timeout: 60s) |
| 11 | `test_load_to_railway_async()` | `POST /load-to-railway/async` | Bearer | Returns `{"job_id": "...", "status": "started"}` |
| 12 | `poll_job()` | `GET /job/{job_id}` | No | Async job reaches completed status within poll window |
| 13 | `test_debug_railway()` | `GET /debug/railway` | Bearer | `{"ok": true, "value": 1}` (WARN on failure, not FAIL) |

**Expected results by environment:**

| Step | Local (no VPN/SQL) | Local (full access) | Railway Production |
|------|-------------------|--------------------|--------------------|
| 01 | PASS | PASS | PASS |
| 02 | PASS (16 tools) | PASS (16 tools) | PASS (15–16 tools) |
| 03 | FAIL (DNS/network) | PASS | PASS |
| 04 | FAIL (no Driver 18) | PASS | PASS |
| 05 | FAIL (depends on 04) | PASS | PASS |
| 06 | FAIL (depends on 05) | PASS | PASS |
| 07 | SKIP (no job_id) | PASS | See known issue |
| 08 | SKIP (no file_id) | PASS | SKIP (depends on 07) |
| 09 | PASS | PASS | PASS |
| 10 | FAIL (no Railway DB) | PASS | PASS |
| 11 | FAIL (no Railway DB) | PASS | PASS |
| 12 | SKIP (no job_id) | PASS | PASS |
| 13 | FAIL/WARN (internal DNS) | PASS | PASS |

### Manual Test Steps (curl equivalents)

Use these when debugging individual endpoints or when the automated runner isn't available.

**Step 1 — Health Check:**
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}
```

**Step 2 — Debug Tools List:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
# Expected: {"tool_count": 16, "tools": [...]}
```

**Step 3 — SQL Server TCP Connectivity:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tcp
# Expected: {"ok": true, "resolved_addresses": [...]}
```

**Step 4 — SQL Server ODBC Connection:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/odbc
# Expected: {"ok": true, "server": "YOUR_SERVER_NAME"}
```

**Step 5 — SQL Server Query:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/sql
# Expected: {"ok": true, "value": 1}
```

**Step 6 — Extract SQL to CSV (starts async job):**
```bash
curl -X POST http://localhost:8000/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS test_column"}'
# Expected: {"job_id": "uuid", "status": "started"}
```

**Step 7 — Poll Job Status:**
```bash
curl http://localhost:8000/job/{job_id}
# Expected: {"status": "completed", "result": {"file_id": "...", "download_url": "..."}}
# Note: No authentication required on this endpoint
```

**Step 8 — File Download:**
```bash
curl "http://localhost:8000/download/{file_id}?token={token_from_download_url}"
# Expected: CSV file content with test_column header
```

**Step 9 — SharePoint Authentication:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/test-sharepoint
# Expected: {"status": "success", "message": "SharePoint auth working"}
```

**Step 10 — Sync SQL to Railway Pipeline:**
```bash
curl -X POST http://localhost:8000/load-to-railway \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "smoke_test_staging"}'
# Expected: {"status": "success", "rows_loaded": 1, ...}
```

**Step 11 — Async SQL to Railway Pipeline:**
```bash
curl -X POST http://localhost:8000/load-to-railway/async \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "smoke_test_staging_async"}'
# Expected: {"job_id": "uuid", "status": "started", "target_table": "smoke_test_staging_async", "status_url": "/job/{job_id}"}
```

**Step 12 — Poll Async Railway Job:**
```bash
curl http://localhost:8000/job/{job_id_from_step_11}
# Expected: {"status": "completed", ...} after background processing completes
```

**Step 13 — Railway DB Connectivity:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/railway
# Expected: {"ok": true, "value": 1}
# Note: Will fail locally if RAILWAY_DB_URL uses internal hostname (postgres.railway.internal)
```

### Additional Manual Tests (not in automated runner)

These endpoints exist in the codebase but are not covered by `cli_tests.py`:

**PostgreSQL Extraction (async job):**
```bash
curl -X POST http://localhost:8000/extract/postgresql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS test_value"}'
# Expected: {"job_id": "uuid", "status": "started"}
# Note: Calls validate_query() at route layer before creating the job
```

**List All Jobs:**
```bash
curl http://localhost:8000/jobs
# Expected: {"jobs": [...], "count": N}
# WARNING: This endpoint currently has NO authentication — see Known Issues
```

**MCP Tool — query_sql_server (via MCP client):**
```json
{
  "tool": "query_sql_server",
  "arguments": {"query": "SELECT TOP 5 * FROM YourTable"}
}
```
*Expected: Markdown table with query results.*

**MCP Tool — list_sharepoint_files (via MCP client):**
```json
{
  "tool": "list_sharepoint_files",
  "arguments": {"folder_path": "Documents"}
}
```
*Expected: List of files and folders with IDs.*

---

## Phase 2: Security & Adversarial Testing

**Goal:** Verify that authentication, input validation, HMAC token security, and concurrency handling work correctly.

**Prerequisites:** Server running locally or on Railway. API_TOKEN set.

### 2.1 Authentication Bypass Tests

Every protected endpoint must reject requests without a valid Bearer token.

| Endpoint | Method | No Token | Wrong Token | Valid Token |
|----------|--------|----------|-------------|-------------|
| `/debug/tools` | GET | 401 | 401 | 200 |
| `/debug/tcp` | GET | 401 | 401 | 200 |
| `/debug/odbc` | GET | 401 | 401 | 200 |
| `/debug/sql` | GET | 401 | 401 | 200 |
| `/debug/railway` | GET | 401 | 401 | 200 |
| `/extract/sql` | POST | 401 | 401 | 200 |
| `/extract/postgresql` | POST | 401 | 401 | 200 |
| `/load-to-railway` | POST | 401 | 401 | 200 |
| `/load-to-railway/async` | POST | 401 | 401 | 200 |
| `/test-sharepoint` | GET | 401 | 401 | 200 |

**Unprotected endpoints (by design):**
- `GET /health` — public health check
- `GET /job/{job_id}` — job status (no auth — see Known Issues)
- `GET /jobs` — job listing (no auth — see Known Issues)
- `GET /download/{file_id}?token=...` — protected by HMAC token, not Bearer token

```bash
# Test: No token
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/debug/tools
# Expected: 401

# Test: Wrong token
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer WRONG" http://localhost:8000/debug/tools
# Expected: 401

# Test: Valid token
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
# Expected: 200
```

### 2.2 SQL Injection / Dangerous Query Tests

The `validate_query()` function in `src/utils/security.py` blocks DDL, DML mutations, multi-statement queries, and comment-hidden dangerous SQL. It is called at the route layer for `/extract/postgresql` and `/load-to-railway/async`, and at the worker layer (inside `SQLServerClient.execute_query_to_dataframe`) for `/extract/sql`.

| Dangerous Query | Expected at `/extract/postgresql` | Expected at `/extract/sql` |
|-----------------|----------------------------------|---------------------------|
| `DROP TABLE users` | 400 (blocked at route) | 200 + job_id (validated later in worker) |
| `DELETE FROM users WHERE 1=1` | 400 | 200 + job_id |
| `TRUNCATE TABLE users` | 400 | 200 + job_id |
| `UPDATE users SET name='x'` | 400 | 200 + job_id |
| `INSERT INTO users VALUES(1)` | 400 | 200 + job_id |
| `ALTER TABLE users ADD col INT` | 400 | 200 + job_id |
| `EXEC xp_cmdshell 'dir'` | 400 | 200 + job_id |
| `SELECT 1; DROP TABLE users` | 400 | 200 + job_id |
| `/**/DROP TABLE users` | 400 | 200 + job_id |
| ` ` (empty/whitespace) | 400 | 400 |

> **Known Issue:** `POST /extract/sql` does not call `validate_query()` at the route layer. The query is validated later in the background worker thread. This means dangerous queries return HTTP 200 with a job_id even though the query will ultimately be rejected. See REPO_DOCUMENTATION.md Section 11 for details.

```bash
# Test: DDL should be rejected
curl -X POST http://localhost:8000/extract/postgresql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "DROP TABLE users"}'
# Expected: 400 with "Dangerous SQL detected" message

# Test: Empty query
curl -X POST http://localhost:8000/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": ""}'
# Expected: 400 "Query cannot be empty"
```

### 2.3 HMAC Download Token Tests

File downloads are protected by HMAC-SHA256 tokens generated by `generate_token()` and validated by `validate_token()` in `src/utils/security.py`.

| Test | Expected |
|------|----------|
| Valid file_id + correct HMAC token | 200 (file download) |
| Valid file_id + garbage token | 403 "Invalid or expired token" |
| Valid file_id + missing token param | 422 (Pydantic validation) |
| Non-existent file_id + valid-looking token | 403 or 404 |

```bash
# Test: Garbage token
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/download/test-file-id?token=garbage"
# Expected: 403

# Test: Missing token
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/download/test-file-id"
# Expected: 422
```

### 2.4 Input Validation Tests

| Test | Endpoint | Payload | Expected |
|------|----------|---------|----------|
| Malformed JSON | `POST /extract/sql` | `{bad json` | 422 |
| Missing required field | `POST /extract/sql` | `{}` | 422 |
| Missing table_name | `POST /load-to-railway` | `{"query": "SELECT 1"}` | 422 |
| Empty query string | `POST /extract/sql` | `{"query": ""}` | 400 |
| Whitespace-only query | `POST /extract/sql` | `{"query": "   "}` | 400 |
| Empty table_name | `POST /load-to-railway/async` | `{"query": "SELECT 1", "table_name": ""}` | 400 |

### 2.5 Concurrency & Stability Tests

| Test | Method | Expected |
|------|--------|----------|
| 50 parallel `GET /health` | Concurrent HTTP | All return 200; p95 latency < 1s locally, < 5s on Railway |
| 10 parallel `GET /debug/tools` | Concurrent HTTP | All return 200 |
| 3 parallel `POST /extract/sql` | Concurrent HTTP | All return 200 + unique job_ids |
| Single `GET /health` | HTTP | Response within 12s (TimeoutMiddleware budget) |
| Single `GET /debug/tools` | HTTP | Response within 12s |
| Single `GET /debug/railway` | HTTP | Response within 13s |

> **Note:** The `TimeoutMiddleware` in `src/main.py` wraps all ASGI requests with a configurable timeout (default: 60 seconds, controlled by `HTTP_REQUEST_TIMEOUT_SECONDS`). Any request exceeding the timeout returns HTTP 504.

---

## Phase 3: GitHub Actions CI (Automated on Every Push)

**Goal:** Ensure Docker builds cleanly and basic endpoint validation works in a CI environment.

**Trigger:** Every push and pull request to `main`.

**CI Workflow File:** `.github/workflows/ci.yml`

### What the CI workflow does:
1. Builds Docker image on an Ubuntu runner with dummy credentials
2. Starts the container and waits for `/health` to respond
3. Tests `/health` returns `{"status": "ok"}`
4. Tests `/debug/tools` returns `tool_count >= 14`
5. If on `main` branch, runs Railway production smoke tests (Phase 4 steps)

### Required Repository Secrets for CI:

| Secret | Purpose | Example |
|--------|---------|---------|
| `API_TOKEN` | Bearer token for smoke tests | `my-secure-token` |
| `RAILWAY_APP_URL` | Live Railway deployment URL | `https://my-app.up.railway.app` |

> **Known Issue:** The current `ci.yml` hardcodes `RAILWAY_URL` instead of using `${{ secrets.RAILWAY_APP_URL }}`. See REPO_DOCUMENTATION.md Section 11 for details.

### CI Decision Gates

| Gate | Criteria | If It Fails |
|------|----------|-------------|
| Build | Docker image builds without errors | Fix Dockerfile or `requirements.txt` |
| Health | Container `/health` responds within 60s | Check `docker logs` for crash output |
| Tools | `/debug/tools` returns >= 14 tools | Check tool registration in `main.py` |

---

## Phase 4: Railway Deployment Smoke Tests (Production Validation)

**Goal:** Verify the deployed app works with production networking, Railway PostgreSQL, and cloud-side credentials.

**When:** After every successful `main` branch CI run (Railway auto-deploys from `main`).

**Automated:** Run `cli_tests.py` against the Railway URL:
```bash
python tests/cli_tests.py --base-url https://your-app.up.railway.app --api-token $API_TOKEN
```

### Manual Railway Test Steps

These mirror Phase 1 but target the production URL. Replace `RAILWAY_URL` with your deployment URL.

**Step 1 — Verify Deployment:**
Check Railway dashboard for "Healthy" deployment status.

**Step 2 — Health Check:**
```bash
curl --retry 10 --retry-delay 5 $RAILWAY_URL/health
# Expected: {"status":"ok"}
```

**Step 3 — Debug Tools:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" $RAILWAY_URL/debug/tools
# Expected: tool_count >= 14
```

**Step 4 — SQL Server TCP (Railway → On-Prem):**
```bash
curl -H "Authorization: Bearer $API_TOKEN" $RAILWAY_URL/debug/tcp
# Expected: {"ok": true} if Railway VPN / firewall allows on-prem access
# Failure here is a NETWORK issue, not a code issue
```

**Step 5 — SQL Server ODBC:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" $RAILWAY_URL/debug/odbc
# Expected: {"ok": true, "server": "YOUR_SERVER"} — confirms ODBC Driver 18 in Docker image
```

**Step 6 — SQL Server Query:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" $RAILWAY_URL/debug/sql
# Expected: {"ok": true, "value": 1}
```

**Step 7 — Extract SQL (async):**
```bash
curl -X POST $RAILWAY_URL/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS test_column"}'
# Expected: {"job_id": "uuid", "status": "started"}
```

**Step 8 — Job Poll:**
```bash
curl $RAILWAY_URL/job/{job_id_from_step_7}
# Expected: {"status": "completed", ...}
# Known Issue: May return 404 — see Known Issues section
```

**Step 9 — File Download:**
```bash
curl "$RAILWAY_URL/download/{file_id}?token={token}"
# Expected: CSV file content
```

**Step 10 — SharePoint Auth:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" $RAILWAY_URL/test-sharepoint
# Expected: {"status": "success", "message": "SharePoint auth working"}
```

**Step 11 — Sync SQL to Railway Pipeline:**
```bash
curl -X POST $RAILWAY_URL/load-to-railway \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "smoke_test_staging"}'
# Expected: {"status": "success", "rows_loaded": 1}
# This is the end-to-end pipeline test: SQL Server → Railway PostgreSQL
```

**Step 12 — Async SQL to Railway Pipeline:**
```bash
curl -X POST $RAILWAY_URL/load-to-railway/async \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS col_a", "table_name": "smoke_test_async"}'
# Expected: {"job_id": "uuid", "status": "started", "target_table": "smoke_test_async"}
```

**Step 13 — Extract PostgreSQL (async):**
```bash
curl -X POST $RAILWAY_URL/extract/postgresql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS test_value"}'
# Expected: {"job_id": "uuid", "status": "started"}
```

**Step 14 — Railway DB Connectivity:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" $RAILWAY_URL/debug/railway
# Expected: {"ok": true, "value": 1}
```

---

## Decision Gates Summary

| Phase | Purpose | Go Criteria | No-Go Action |
|-------|---------|-------------|--------------|
| 1. Local Smoke | Catch code bugs and routing issues | `/health` responds; debug endpoints work with real credentials | Fix code locally. Do NOT push to main. |
| 2. Security | Verify auth and input validation | All protected endpoints reject no-auth; dangerous SQL blocked; HMAC tokens validated | Fix security gaps before deployment. |
| 3. CI | Validate Docker build automation | Image builds; container starts; health check passes | Fix Dockerfile or OS-level dependencies. |
| 4. Railway | Validate production behavior | `/health` responds; DB connectivity works; full pipeline executes | Check Railway env vars, firewall, DNS. |

---

## Known Issues

These are documented defects that affect test expectations:

| # | Issue | Severity | Impact on Tests |
|---|-------|----------|----------------|
| 1 | `GET /jobs` has no `require_api_token` guard | HIGH | Auth bypass tests will show 200 instead of 401 for this endpoint |
| 2 | `POST /extract/sql` skips `validate_query()` at route layer | MEDIUM | Dangerous SQL queries return 200 + job_id (blocked later in worker) |
| 3 | `GET /job/{job_id}` may return 404 for valid job IDs on Railway | MEDIUM | Step 8 (job poll) may fail in production despite job being created |
| 4 | `ci.yml` hardcodes `RAILWAY_URL` instead of using secrets | LOW | CI Railway smoke tests may target wrong URL if deployment changes |

---

## Environment Variables Reference

### Application Configuration (.env file)

**Core Settings:**

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SQL_SERVER_HOST` | — | Yes | On-premises SQL Server hostname or IP |
| `SQL_SERVER_PORT` | `1433` | No | SQL Server port |
| `SQL_SERVER_DB` | — | Yes | SQL Server database name |
| `SQL_SERVER_USER` | — | Yes | SQL Server username |
| `SQL_SERVER_PASSWORD` | — | Yes | SQL Server password |
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` | No | ODBC driver name (use Driver 17 locally if 18 is not installed) |
| `RAILWAY_DB_URL` | — | Yes | Full PostgreSQL connection string for Railway |
| `SP_TENANT_ID` | — | Yes | Microsoft Entra (Azure AD) tenant ID |
| `SP_CLIENT_ID` | — | Yes | SharePoint app registration client ID |
| `SP_CLIENT_SECRET` | — | Yes | SharePoint app registration client secret |
| `SP_SITE_ID` | — | Yes | SharePoint site ID |
| `SP_DRIVE_ID` | — | Yes | SharePoint document library drive ID |
| `API_TOKEN` | — | Yes | Bearer token for REST API authentication |
| `DOWNLOAD_TOKEN_SECRET` | — | Yes | HMAC-SHA256 secret for download URLs (min 10 chars) |
| `LOG_LEVEL` | `INFO` | No | Python logging level |
| `OUTPUT_DIR` | `/app/output_files` | No | Directory for generated CSV files |
| `APP_BASE_URL` | `http://localhost:8000` | No | Base URL for constructing download links |

**Timeout & Performance Tuning:**

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_REQUEST_TIMEOUT_SECONDS` | `60` | TimeoutMiddleware budget for all HTTP requests |
| `SQL_SERVER_CONNECT_TIMEOUT_SECONDS` | `10` | pyodbc connection timeout |
| `SQL_SERVER_LOGIN_TIMEOUT_SECONDS` | `10` | pyodbc login timeout |
| `SQL_SERVER_POOL_TIMEOUT_SECONDS` | `30` | Connection pool wait timeout |
| `SQL_SERVER_PREVIEW_TIMEOUT_SECONDS` | `30` | Timeout for preview/debug queries |
| `SQL_SERVER_EXTRACT_TIMEOUT_SECONDS` | `300` | Timeout for full extraction queries |
| `SQL_SERVER_FORCE_ABORT_SECONDS` | `0` | Force-abort long queries (0 = disabled) |
| `RAILWAY_CONNECT_TIMEOUT_SECONDS` | `10` | PostgreSQL connection timeout |
| `RAILWAY_QUERY_STATEMENT_TIMEOUT_MS` | `30000` | PostgreSQL statement_timeout for queries (ms) |
| `RAILWAY_EXPORT_STATEMENT_TIMEOUT_MS` | `0` | PostgreSQL timeout for exports (0 = unlimited) |
| `RAILWAY_INSERT_CHUNKSIZE` | `500` | Rows per INSERT batch during Railway staging |

### GitHub Actions Secrets

| Secret | Purpose |
|--------|---------|
| `API_TOKEN` | Bearer token for CI smoke tests |
| `RAILWAY_APP_URL` | Production Railway URL for Phase 4 tests |

### Railway Dashboard Variables

Same as the `.env` variables above, but with production values. Railway injects these into the container at runtime.

---

## Troubleshooting Guide

| Symptom | Likely Phase | Cause | Fix |
|---------|-------------|-------|-----|
| Docker build fails | 1 (Local) | Missing apt package or Python dependency | Check Dockerfile `apt-get install` and `requirements.txt` |
| `/health` times out | 1 (Local) | Port mapping wrong or app crashed on startup | Check `docker logs` or server stdout; verify `-p 8000:8000` |
| `pyodbc` import error | 1 (Local) | ODBC driver not installed | Install `msodbcsql18` (Docker) or `msodbcsql17` (local dev) |
| `psycopg2` wheel error | 1 (Local) | No pre-built wheel for your Python version | Use `psycopg2-binary>=2.9.10` or build from source |
| SQL tests FAIL locally | 1 (Local) | DB_DRIVER mismatch or no VPN to on-prem SQL | Set `DB_DRIVER=ODBC Driver 17 for SQL Server` in `.env` |
| Railway DB FAIL locally | 1 (Local) | `postgres.railway.internal` is Railway-internal DNS | Expected — only resolvable inside Railway's network |
| CI build fails | 3 (CI) | OS-specific Docker issue | Test `docker build` on a fresh Ubuntu VM |
| CI `/health` timeout | 3 (CI) | Container exits immediately | Add `docker logs` step to CI workflow |
| Railway 502/503 | 4 (Railway) | App crashed or deploy pending | Check Railway dashboard logs |
| Railway SQL timeout | 4 (Railway) | Firewall blocking Railway → on-prem | Allowlist Railway outbound IPs or configure VPN |
| SharePoint 401 | 4 (Railway) | Token expired or Graph permissions missing | Renew client secret; grant admin consent in Azure portal |
| Job stays "running" | 4 (Railway) | Background thread crashed | Check server logs; restart deployment |
| `/job/{id}` returns 404 | 4 (Railway) | Known issue with async job tracking | See Known Issues table above |
| Dangerous SQL returns 200 | 2 (Security) | `/extract/sql` skips route-level validation | Known issue — see Known Issues table |
| `/jobs` returns 200 without auth | 2 (Security) | Missing `require_api_token` guard | Known issue — see Known Issues table |

---

## Test Commands Quick Reference

### Local (localhost:8000)
```bash
# Health & Debug
curl http://localhost:8000/health
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tcp
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/odbc
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/sql
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/railway

# Extraction & Pipeline
curl -X POST http://localhost:8000/extract/sql -H "Content-Type: application/json" -H "Authorization: Bearer $API_TOKEN" -d '{"query": "SELECT 1 AS test_column"}'
curl -X POST http://localhost:8000/extract/postgresql -H "Content-Type: application/json" -H "Authorization: Bearer $API_TOKEN" -d '{"query": "SELECT 1 AS test_value"}'
curl -X POST http://localhost:8000/load-to-railway -H "Content-Type: application/json" -H "Authorization: Bearer $API_TOKEN" -d '{"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "test_staging"}'
curl -X POST http://localhost:8000/load-to-railway/async -H "Content-Type: application/json" -H "Authorization: Bearer $API_TOKEN" -d '{"query": "SELECT 1 AS col_a", "table_name": "test_async"}'

# Job & Download
curl http://localhost:8000/job/{job_id}
curl http://localhost:8000/jobs
curl "http://localhost:8000/download/{file_id}?token={token}"

# SharePoint
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/test-sharepoint
```

### Railway (Production)
Replace `http://localhost:8000` with `https://<your-app>.up.railway.app` in all commands above.

### Automated Suite
```bash
# Local
python tests/cli_tests.py --base-url http://localhost:8000 --api-token $API_TOKEN

# Railway
python tests/cli_tests.py --base-url https://your-app.up.railway.app --api-token $API_TOKEN

# Stop on first failure
python tests/cli_tests.py --stop-on-failure
```

---

*Document generated for SQL-Analysis repository. Last updated: May 2026.*
