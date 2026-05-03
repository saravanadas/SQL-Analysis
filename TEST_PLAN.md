# UnifiedDataMCP — Complete Test Plan

## Philosophy: Local First, Then Cloud

**Local Smoke Tests** catch code bugs, syntax errors, and FastAPI routing issues BEFORE you waste a deployment cycle.
**GitHub Actions CI** validates that the Docker build works in a clean environment and automates the process.
**Railway Smoke Tests** validate the ONLY thing that matters: does it work in production?

---

## Phase 1: Local Smoke Tests (Developer Machine)

**Goal:** Verify the app starts, endpoints respond, and code logic is correct.
**Prerequisites:** Docker installed, .env file configured with real credentials.

### Automated Test Runner (Recommended)
Instead of running curl commands manually, use the Python smoke test suite:
```bash
# Set your API token in the environment
$env:API_TOKEN = "your-api-token-here"

# Run the full suite against a running local server
python tests/cli_tests.py

# Override defaults via CLI
python tests/cli_tests.py --base-url http://localhost:8000 --api-token mytoken

# Or run with pytest
pytest tests/cli_tests.py -v
```

### Step 1: Build Docker Image
```bash
cd SQL-Analysis
docker build -t unified-mcp .
```
**Gate:** Build must succeed. If it fails here, fix Dockerfile before proceeding.

### Step 2: Start Container
```bash
docker run -p 8000:8000 --env-file .env unified-mcp
```
**Gate:** Logs must show "MCP mounted successfully at /mcp" and "Scheduler started".

### Step 3: Health Check
```bash
curl http://localhost:8000/health
```
**Expected:** `{"status": "ok"}`

### Step 4: Debug Tools List
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
```
**Expected:** JSON with `tool_count` >= 14 and full list of tool names.

### Step 5: SQL Server TCP Connectivity
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tcp
```
**Expected:** `{"ok": true, ...}` with resolved IP addresses.

### Step 6: SQL Server ODBC Connection
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/odbc
```
**Expected:** `{"ok": true, "server": "YOUR_SERVER_NAME"}`

### Step 7: SQL Server Query Test
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/sql
```
**Expected:** `{"ok": true, "value": 1}`

### Step 8: REST API Extract SQL to CSV
```bash
curl -X POST http://localhost:8000/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT TOP 10 * FROM YourTable"}'
```
**Expected:** `{"job_id": "uuid", "status": "started"}`

### Step 9: Job Status Check
```bash
curl http://localhost:8000/job/{job_id_from_test_8}
```
**Expected:** After completion: `{"status": "completed", "result": {...}}`

### Step 10: File Download
```bash
curl "http://localhost:8000/download/{file_id}?token={token}"
```
**Expected:** CSV file download with correct data.

### Step 11: SharePoint Token Test
```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/test-sharepoint
```
**Expected:** `{"status": "success", "message": "SharePoint auth working"}`

### Step 12: MCP Tool — query_sql_server
Use an MCP client (e.g., Claude Desktop):
```json
{
  "tool": "query_sql_server",
  "arguments": {
    "query": "SELECT TOP 5 * FROM YourTable"
  }
}
```
**Expected:** Markdown table with first 5 rows.

### Step 13: MCP Tool — list_sharepoint_files
```json
{
  "tool": "list_sharepoint_files",
  "arguments": {
    "folder_path": "Documents"
  }
}
```
**Expected:** List of files and folders with IDs.

### Step 14: SQL to Railway Pipeline
```bash
curl -X POST http://localhost:8000/load-to-railway \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{
    "query": "SELECT TOP 100 * FROM YourTable",
    "table_name": "test_staging"
  }'
```
**Expected:** `{"status": "success", "rows_loaded": 100, ...}`

### Step 15: SharePoint to Railway Pipeline
Use MCP client:
```json
{
  "tool": "sharepoint_to_railway",
  "arguments": {
    "folder_path": "Data/Uploads",
    "table_name": "uploaded_data"
  }
}
```
**Expected:** Success message with row count.

### Step 16: Stop Container
```bash
Ctrl+C or docker stop <container_id>
```

---

## Phase 2: GitHub Actions CI (Automated on Every Push)

**Goal:** Ensure Docker builds cleanly and basic endpoint validation works in a CI environment.
**Trigger:** Every push and PR to main.

### What the CI workflow does:
1. Builds Docker image on an Ubuntu runner
2. Runs the container with dummy/test credentials
3. Tests `/health` and `/debug/tools` locally
4. If on `main` branch, proceeds to Phase 3

### CI Workflow File
`.github/workflows/ci.yml` (already created in this repo)

### Required Repository Secrets for CI:
- `RAILWAY_APP_URL` — Your live Railway URL (e.g., `https://my-app.up.railway.app`)
- `API_TOKEN` — Production API token for smoke tests

### CI Decision Gates
| Gate | Criteria |
|------|----------|
| Build | Docker image builds without errors |
| Health | Container starts and `/health` responds within 60 seconds |
| Tools | `/debug/tools` returns >= 14 registered tools |

---

## Phase 3: Railway Deployment Smoke Tests (Production Validation)

**Goal:** Verify the deployed app on Railway works with production networking, Railway PostgreSQL, and cloud-side credentials.
**When:** After every successful `main` branch CI run (auto-deploy via Railway + CI smoke tests).

### Step 1: Verify Railway Auto-Deployment
Railway auto-deploys from `main` branch. Check Railway dashboard for deployment status.
**Gate:** Deployment must show "Healthy" in Railway dashboard.

### Step 2: Poll Live Health Endpoint
```bash
curl --retry 10 --retry-delay 5 https://<your-railway-app>.up.railway.app/health
```
**Gate:** Must return `{"status": "ok"}`.

### Step 3: Health Check (Railway)
```bash
curl https://<your-railway-app>.up.railway.app/health
```
**Expected:** `{"status": "ok"}`

### Step 4: Debug Tools List (Railway)
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  https://<your-railway-app>.up.railway.app/debug/tools
```
**Expected:** JSON with `tool_count` >= 14.

### Step 5: Debug TCP Connectivity (Railway)
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  https://<your-railway-app>.up.railway.app/debug/tcp
```
**Expected:** `{"ok": true, ...}` OR failure if on-prem SQL Server blocks Railway IPs.
**Note:** Failure here is EXPECTED if your on-prem SQL Server does not allow connections from Railway's cloud IPs. This is a network/firewall issue, not a code issue.

### Step 6: Debug ODBC Connectivity (Railway)
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  https://<your-railway-app>.up.railway.app/debug/odbc
```
**Expected:** `{"ok": true, "server": "YOUR_SERVER_NAME"}` OR failure.
**Note:** Same network/firewall caveat as Test 5.

### Step 7: Debug SQL Query (Railway)
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  https://<your-railway-app>.up.railway.app/debug/sql
```
**Expected:** `{"ok": true, "value": 1}` OR failure.
**Note:** Depends on Tests 5 and 6 passing.

### Step 8: REST API Extract SQL (Railway)
```bash
curl -X POST https://<your-railway-app>.up.railway.app/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS test_column"}'
```
**Expected:** `{"job_id": "uuid", "status": "started"}` OR failure if SQL Server unreachable.

### Step 9: Job Status Check (Railway)
```bash
curl https://<your-railway-app>.up.railway.app/job/{job_id_from_test_8}
```
**Expected:** After completion: `{"status": "completed", ...}`

### Step 10: SharePoint Token Test (Railway)
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  https://<your-railway-app>.up.railway.app/test-sharepoint
```
**Expected:** `{"status": "success", ...}` OR failure if SharePoint credentials/permissions are misconfigured.

### Step 11-14: MCP Tool Tests (Railway)
Same tools as Phase 1 Tests 12-15, but executed via MCP client pointing at the Railway-hosted MCP endpoint (`https://<your-app>.up.railway.app/mcp`).

---

## Decision Gates Summary

| Phase | Purpose | Go/No-Go Criteria | If It Fails |
|-------|---------|-------------------|-------------|
| 1. Local | Catch code bugs, syntax errors, routing issues | Docker builds, `/health` responds, debug endpoints work with real credentials | Fix code/Dockerfile locally. Do NOT push to main. |
| 2. CI | Validate build automation, catch environment-specific build issues | Docker builds in clean CI environment, local health check passes | Check Dockerfile for OS-specific deps (e.g., msodbcsql18) |
| 3. Railway | Validate production behavior: networking, DB connectivity, cloud secrets | `/health` on Railway responds, DB connectivity from cloud works | Check Railway env vars, firewall rules, database connection strings |

---

## Environment Variables Reference

### Required for Local Testing (.env file)
```env
SQL_SERVER_HOST=your-sql-server.company.com
SQL_SERVER_PORT=1433
SQL_SERVER_DB=ProductionDB
SQL_SERVER_USER=sa
SQL_SERVER_PASSWORD=YourStrongPassword
DB_DRIVER=ODBC Driver 18 for SQL Server
RAILWAY_DB_URL=postgresql://user:pass@host:5432/dbname
SP_TENANT_ID=your-tenant-id
SP_CLIENT_ID=your-app-client-id
SP_CLIENT_SECRET=your-app-secret
SP_SITE_ID=your-site-id
SP_DRIVE_ID=your-drive-id
API_TOKEN=your-secure-api-token
DOWNLOAD_TOKEN_SECRET=your-secret-for-download-tokens-min-10-chars
LOG_LEVEL=INFO
OUTPUT_DIR=/app/output_files
APP_BASE_URL=http://localhost:8000
```

### Required for Railway (Dashboard Secrets)
Same variables as above, but with production values. Railway auto-injects these into the container at runtime.

### Required for GitHub Actions (Repository Secrets)
```
RAILWAY_APP_URL=https://your-app.up.railway.app
API_TOKEN=your-production-api-token
```

---

## Troubleshooting Guide

| Symptom | Likely Phase | Cause | Fix |
|---------|-------------|-------|-----|
| Docker build fails | 1 (Local) | Missing dependency in Dockerfile | Add missing apt packages or Python libs |
| `/health` times out | 1 (Local) | Port mapping wrong or app crashed | Check `docker logs`, verify `-p 8000:8000` |
| `pyodbc` import error | 1 (Local) | ODBC driver not installed locally | Install `msodbcsql18` or use Docker |
| CI build fails | 2 (CI) | Dockerfile has OS-specific issues | Test `docker build` on a fresh Ubuntu VM |
| CI `/health` fails | 2 (CI) | Container exits immediately | Add `docker logs` step to CI for debugging |
| Railway 502/503 | 3 (Railway) | App crashed or failed to start | Check Railway dashboard logs |
| Railway `/health` fails | 3 (Railway) | Env vars missing in Railway dashboard | Add all required secrets to Railway |
| SQL connection timeout (Railway) | 3 (Railway) | Firewall blocking Railway IPs | Allowlist Railway outbound IPs or use VPN |
| SharePoint 401 (Railway) | 3 (Railway) | Token expired or permissions missing | Renew client secret, grant admin consent |
| Job stays "running" forever | 3 (Railway) | Background thread crashed | Check Railway logs, restart deployment |

---

## Test Commands Quick Reference

### Local (localhost:8000)
```bash
curl http://localhost:8000/health
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tcp
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/odbc
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/sql
curl -X POST http://localhost:8000/extract/sql -H "Content-Type: application/json" -H "Authorization: Bearer $API_TOKEN" -d '{"query": "SELECT TOP 10 * FROM YourTable"}'
curl http://localhost:8000/job/{job_id}
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/test-sharepoint
curl -X POST http://localhost:8000/load-to-railway -H "Content-Type: application/json" -H "Authorization: Bearer $API_TOKEN" -d '{"query": "SELECT TOP 100 * FROM YourTable", "table_name": "test_staging"}'
```

### Railway (Production)
Replace `http://localhost:8000` with `https://<your-app>.up.railway.app` in all commands above.

---

*Document generated for SQL-Analysis repository. Last updated: May 2026.*
