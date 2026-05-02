# SQL-Analysis Repository Documentation
## Unified SQL MCP - Comprehensive Technical Guide

---

## 1. Project Overview

The **UnifiedDataMCP** is a Model Context Protocol (MCP) server built with FastAPI that acts as a secure bridge between:
- **On-premises Microsoft SQL Server** (via pyodbc)
- **SharePoint Online** (via Microsoft Graph API)
- **Railway-hosted PostgreSQL** (analytical staging database)

It exposes both **REST API endpoints** and **MCP tools** that allow AI agents to query SQL Server, extract data to CSV, stage data to PostgreSQL, and interact with SharePoint files.

---

## 2. Architecture & Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web Framework | FastAPI | HTTP API layer |
| MCP Framework | FastMCP (v2+) | Model Context Protocol tool registration |
| Database Engine | SQLAlchemy | Connection pooling & ORM-like operations |
| SQL Server Driver | pyodbc | On-prem SQL Server connectivity |
| PostgreSQL Driver | psycopg2-binary | Railway DB connectivity |
| Data Processing | pandas | DataFrame manipulation & CSV export |
| SharePoint API | requests + Microsoft Graph API | File listing, download, metadata |
| PDF Processing | pypdf | Server-side PDF text extraction |
| Job Scheduling | APScheduler | Background cleanup & periodic tasks |
| Configuration | pydantic-settings | Environment-based config with validation |
| Security | HMAC-SHA256 | Secure download token generation |
| Deployment | Docker + Railway | Containerized cloud deployment |

---

## 3. Directory Structure

```
src/
├── main.py                  # FastAPI app, MCP initialization, debug endpoints
├── api/
│   └── routes.py            # REST API endpoints
├── config/
│   ├── settings.py          # Pydantic-based configuration & validation
│   └── database.py          # Railway PostgreSQL engine factory
├── engine/
│   └── job_manager.py       # Background job execution (thread-based)
├── services/
│   ├── file_manager.py      # CSV generation, temp file cleanup
│   ├── sql_server_client.py # SQL Server connection & chunked querying
│   ├── railway_db_client.py # PostgreSQL data staging & tracking tables
│   └── sharepoint_client.py # SharePoint Graph API integration
├── tools/
│   ├── database_tools.py    # MCP tool registration: SQL/DB operations
│   └── sharepoint_tools.py  # MCP tool registration: SharePoint operations
└── utils/
    ├── security.py          # Token generation, query validation
    ├── logger.py            # STDOUT logging for Railway
    ├── retry.py             # Retry decorator for transient failures
    ├── data_validator.py    # DataFrame validation & cleaning
    └── scheduler.py         # SharePoint ingestion scheduler
```

---

## 4. Component Deep Dive

### 4.1 `main.py` - Application Entry Point

**Responsibilities:**
- Initializes the FastMCP instance (`UnifiedDataMCP`)
- Registers all database and SharePoint tools
- Creates the FastAPI app with lifespan management
- Mounts the MCP HTTP app at `/mcp`
- Runs background cleanup scheduler (hourly)
- Provides debug endpoints for connectivity testing

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `create_mcp()` | Creates and configures the FastMCP instance |
| `cleanup_job()` | Removes temp files older than 1 hour |
| `lifespan()` | Async context manager for scheduler startup/shutdown |
| `health()` | Returns `{"status": "ok"}` |
| `debug_tools()` | Lists all registered MCP tools (auth required) |
| `debug_tcp()` | Tests TCP connectivity to SQL Server host |
| `debug_odbc()` | Tests pyodbc connection to SQL Server |
| `debug_sql()` | Executes `SELECT 1` via pyodbc |
| `main()` | Starts uvicorn server on `0.0.0.0:PORT` |

**Authentication:** Debug endpoints require `Authorization: Bearer <API_TOKEN>` header.

---

### 4.2 `api/routes.py` - REST API Endpoints

**Router:** `APIRouter()` mounted at app root.

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/health` | GET | Health check | None |
| `/load-to-railway` | POST | Trigger SQL Server → Railway pipeline | Bearer Token |
| `/extract/sql` | POST | Start async SQL extraction job | Bearer Token |
| `/job/{job_id}` | GET | Get job status & result | None |
| `/test-sharepoint` | GET | Test SharePoint token acquisition | Bearer Token |
| `/download/{file_id}` | GET | Download generated CSV file | Token in query param |

**Key Classes:**
- `LoadRequest`: Pydantic model with `query` and `table_name`
- `SQLRequest`: Pydantic model with `query`

**Key Functions:**
- `process_sql_job()`: Background worker that executes SQL, writes CSV, returns download URL
- `require_api_token()`: Validates `Authorization: Bearer <API_TOKEN>` header

---

### 4.3 `config/settings.py` - Configuration Management

**Class:** `Settings(BaseSettings)`

Loads configuration from environment variables or `.env` file with Pydantic validation.

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `SQL_SERVER_HOST` | str | **Required** | Non-empty |
| `SQL_SERVER_PORT` | int | 1433 | - |
| `SQL_SERVER_DB` | str | **Required** | Non-empty |
| `SQL_SERVER_USER` | str | **Required** | Non-empty |
| `SQL_SERVER_PASSWORD` | str | **Required** | - |
| `DB_DRIVER` | str | "ODBC Driver 18 for SQL Server" | - |
| `RAILWAY_DB_URL` | str | **Required** | Must start with `postgresql://` |
| `SP_TENANT_ID` | str | **Required** | Non-empty |
| `SP_CLIENT_ID` | str | **Required** | Non-empty |
| `SP_CLIENT_SECRET` | str | **Required** | Non-empty |
| `SP_SITE_ID` | str | **Required** | Non-empty |
| `SP_DRIVE_ID` | str | **Required** | Non-empty |
| `LOG_LEVEL` | str | "INFO" | - |
| `OUTPUT_DIR` | str | "/app/output_files" | Non-empty |
| `APP_BASE_URL` | str | "http://localhost:8000" | - |
| `API_TOKEN` | str | **Required** | - |
| `DOWNLOAD_TOKEN_SECRET` | str | **Required** | Min 10 chars |

---

### 4.4 `config/database.py` - Railway Engine

**Function:** `get_engine()`

Creates a SQLAlchemy engine using `settings.railway_db_url` with `pool_pre_ping=True`.

---

### 4.5 `engine/job_manager.py` - Background Jobs

**Class:** `JobManager`

Uses PostgreSQL `jobs` table for persistent job tracking and Python `threading` for execution.

| Method | Purpose |
|--------|---------|
| `create_job(func, *args)` | Creates job record, spawns thread, returns job_id |
| `run_job(job_id, func, args)` | Executes function, updates DB with result/error |
| `get_job(job_id)` | Retrieves job status/result from PostgreSQL |

**Job States:** `running`, `completed`, `failed`

---

### 4.6 `services/file_manager.py` - File Operations

**Class:** `FileManager`

Handles temp file generation, cleanup, and secure download preparation.

| Method | Purpose |
|--------|---------|
| `generate_csv_from_dataframe(df, base_filename)` | Creates timestamped CSV from DataFrame |
| `get_file_content_base64(filepath)` | Converts file to base64 for MCP transmission |
| `generate_file_id()` | Returns UUID for unique file identification |
| `get_file_path(file_id, extension)` | Builds path with given extension |
| `get_file(file_id)` | Searches output_dir for matching file |
| `cleanup_old_files(hours)` | Deletes files older than N hours |
| `write_csv_stream(file_path, generator)` | Memory-efficient streaming CSV writer |

---

### 4.7 `services/sql_server_client.py` - SQL Server

**Class:** `SQLServerClient`

Connects to on-premises SQL Server via pyodbc with connection pooling.

| Method | Purpose |
|--------|---------|
| `execute_query_to_dataframe(query, chunksize)` | Streaming query execution (yields DataFrames) |

**Connection Features:**
- `fast_executemany=True` for bulk operations
- `pool_pre_ping=True` for health checks
- `pool_recycle=1800` to prevent stale connections
- `@retry` decorator (3 attempts, 3s delay)

---

### 4.8 `services/railway_db_client.py` - PostgreSQL

**Class:** `RailwayDBClient`

Manages the analytical staging database on Railway.

| Method | Purpose |
|--------|---------|
| `stage_dataframe(df, table_name, if_exists)` | Loads DataFrame to PostgreSQL |
| `insert_dataframe_chunked(df, table_name, mode)` | Chunk-safe insert with mode switching |
| `bulk_insert(df, table_name)` | Optimized bulk insert (append mode) |
| `ensure_tracking_table()` | Creates `mcp_file_tracking` table |
| `is_file_processed(file_name)` | Checks if file already ingested |
| `mark_file_processed(file_name)` | Marks file as processed |
| `ensure_pdf_text_table(table_name)` | Creates table for PDF page text |
| `ensure_invoice_file_table(table_name)` | Creates table for PDF metadata |
| `upsert_invoice_file_record(record, table_name)` | Insert/update PDF metadata |
| `store_pdf_text_rows(rows, table_name)` | Stores extracted PDF text pages |
| `execute_query(query)` | Executes SELECT and returns DataFrame |

---

### 4.9 `services/sharepoint_client.py` - SharePoint

**Class:** `SharePointClient`

Integrates with SharePoint via Microsoft Graph API using client credentials flow.

| Method | Purpose |
|--------|---------|
| `_get_access_token()` | OAuth2 client credentials token acquisition |
| `_headers()` | Returns Bearer token headers (auto-refresh) |
| `list_files(folder_path, max_items)` | Lists files with pagination (200 default limit) |
| `list_files_recursive(folder_path, max_items)` | Recursively walks folders |
| `download_file(download_url)` | Downloads file bytes |
| `get_file_metadata(file_id)` | Fetches file metadata & download URL |

---

### 4.10 `tools/database_tools.py` - MCP Database Tools

**Tools Registered:**

| Tool Name | Purpose | Parameters |
|-----------|---------|------------|
| `query_sql_server` | Execute SELECT on SQL Server | `query: str` |
| `extract_sql_to_csv` | Extract to CSV with download link | `query: str` |
| `stage_sql_to_railway` | Transfer SQL Server → Railway | `query: str`, `target_table: str` |
| `query_analytical_db` | Query Railway PostgreSQL | `query: str` |

**Shared Function:**
- `load_sql_to_railway(query, table_name)`: Core pipeline logic used by both MCP tool and REST API

---

### 4.11 `tools/sharepoint_tools.py` - MCP SharePoint Tools

**Tools Registered:**

| Tool Name | Purpose | Parameters |
|-----------|---------|------------|
| `ingest_sharepoint_invoice_pdfs_to_railway` | Bulk PDF ingestion with deduplication | `folder_path`, `batch_number`, `max_files`, `force_reprocess`, `pdf_text_table`, `file_table` |
| `ingest_invoice_pdfs` | Short alias for above | Same as above (simplified) |
| `search_sharepoint_pdfs_recursive` | Find invoice PDFs recursively | `folder_path`, `batch_number`, `max_items` |
| `extract_sharepoint_pdf_text` | Download & extract PDF text preview | `file_id`, `file_name`, `max_preview_chars` |
| `stage_sharepoint_pdf_text_to_railway` | Extract & store PDF text in PostgreSQL | `file_id`, `file_name`, `sharepoint_path`, `table_name` |
| `stage_invoice_lines_to_railway` | Store parsed invoice data | `rows: list[dict]`, `table_name`, `mode` |
| `list_sharepoint_files` | List files in folder | `folder_path` |
| `download_sharepoint_file` | Download single file | `file_id`, `file_name` |
| `download_sharepoint_folder` | Download all files in folder | `folder_path` |
| `sharepoint_to_railway` | CSV/Excel ingestion pipeline | `folder_path`, `table_name` |

---

### 4.12 `utils/security.py` - Security Utilities

| Function | Purpose |
|----------|---------|
| `generate_token(file_name, expiry_minutes)` | HMAC-SHA256 signed download token |
| `validate_token(file_name, token)` | Validates token signature & expiry |
| `validate_query(query)` | SQL injection prevention (SELECT-only, blocks DDL/DML) |

**Query Validation Rules:**
- Must start with `SELECT`
- Blocks: DROP, DELETE, TRUNCATE, ALTER, UPDATE, INSERT, EXEC, MERGE
- No multiple statements (`;` forbidden)
- Comments are stripped before validation

---

### 4.13 `utils/logger.py` - Logging

**Function:** `setup_logger(name)`

- STDOUT output for Railway log aggregation
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- Singleton pattern (prevents duplicate handlers)

---

### 4.14 `utils/retry.py` - Retry Decorator

**Decorator:** `@retry(max_attempts=3, delay=2)`

Wraps functions with exponential-like retry logic for transient failures (DB connections, network, etc.).

---

### 4.15 `utils/data_validator.py` - Data Cleaning

**Function:** `validate_dataframe(df)`

- Removes empty rows (`dropna(how="all")`)
- Trims column names
- Removes duplicates

---

### 4.16 `utils/scheduler.py` - Background Scheduling

**Function:** `start_scheduler()`

Starts APScheduler with a daily SharePoint ingestion job (Finance/Reports → `finance_reports` table).

---

## 5. Environment Variables Quick Reference

Create a `.env` file with:

```env
# SQL Server (On-Premises)
SQL_SERVER_HOST=your-sql-server.company.com
SQL_SERVER_PORT=1433
SQL_SERVER_DB=ProductionDB
SQL_SERVER_USER=sa
SQL_SERVER_PASSWORD=YourStrongPassword
DB_DRIVER=ODBC Driver 18 for SQL Server

# Railway PostgreSQL
RAILWAY_DB_URL=postgresql://user:pass@host:5432/dbname

# SharePoint (Microsoft Graph API)
SP_TENANT_ID=your-tenant-id
SP_CLIENT_ID=your-app-client-id
SP_CLIENT_SECRET=your-app-secret
SP_SITE_ID=your-site-id
SP_DRIVE_ID=your-drive-id

# Application
API_TOKEN=your-secure-api-token
DOWNLOAD_TOKEN_SECRET=your-secret-for-download-tokens-min-10-chars
LOG_LEVEL=INFO
OUTPUT_DIR=/app/output_files
APP_BASE_URL=https://your-app.railway.app
```

---

## 6. Smoke Test Plan

### 6.1 Prerequisites

1. Docker installed locally (or Python 3.11+)
2. All environment variables configured
3. SQL Server accessible from test machine
4. SharePoint app registration with client credentials

### 6.2 Test 1: Application Startup

```bash
# Build and run
docker build -t unified-mcp .
docker run -p 8000:8000 --env-file .env unified-mcp

# Or locally:
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

**Expected:** Server starts without errors, logs show "MCP mounted successfully at /mcp".

---

### 6.3 Test 2: Health Check

```bash
curl http://localhost:8000/health
```

**Expected:** `{"status": "ok"}`

---

### 6.4 Test 3: Debug Tools List

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
```

**Expected:** JSON with `tool_count` >= 14 and full list of tool names.

---

### 6.5 Test 4: SQL Server Connectivity (Debug TCP)

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tcp
```

**Expected:** `{"ok": true, ...}` with resolved IP addresses.

---

### 6.6 Test 5: SQL Server Query (Debug ODBC)

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/odbc
```

**Expected:** `{"ok": true, "server": "YOUR_SERVER_NAME"}`

---

### 6.7 Test 6: SQL Server Query (Debug SQL)

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/sql
```

**Expected:** `{"ok": true, "value": 1}`

---

### 6.8 Test 7: REST API - Extract SQL to CSV

```bash
curl -X POST http://localhost:8000/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT TOP 10 * FROM YourTable"}'
```

**Expected:** `{"job_id": "uuid", "status": "started"}`

---

### 6.9 Test 8: Job Status Check

```bash
curl http://localhost:8000/job/{job_id_from_test_7}
```

**Expected:** After completion: `{"status": "completed", "result": {...}}`

---

### 6.10 Test 9: File Download

Use the download URL from job result or:
```bash
curl "http://localhost:8000/download/{file_id}?token={token}"
```

**Expected:** CSV file download with correct data.

---

### 6.11 Test 10: SharePoint Token Test

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/test-sharepoint
```

**Expected:** `{"status": "success", "message": "SharePoint auth working"}`

---

### 6.12 Test 11: MCP Tool - query_sql_server

Use an MCP client (e.g., Claude Desktop with MCP config):

```json
{
  "tool": "query_sql_server",
  "arguments": {
    "query": "SELECT TOP 5 * FROM YourTable"
  }
}
```

**Expected:** Markdown table with first 5 rows.

---

### 6.13 Test 12: MCP Tool - list_sharepoint_files

```json
{
  "tool": "list_sharepoint_files",
  "arguments": {
    "folder_path": "Documents"
  }
}
```

**Expected:** List of files and folders with IDs.

---

### 6.14 Test 13: SQL → Railway Pipeline

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

---

### 6.15 Test 14: SharePoint → Railway Pipeline

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

---

## 7. Deployment Notes

### Docker Build
```bash
docker build -t unified-mcp .
```

### Railway Deployment
1. Push to GitHub
2. Connect Railway to repo
3. Set all environment variables in Railway dashboard
4. Deploy automatically via `railway.toml`

### SharePoint App Registration Requirements
- **Application (client) ID**
- **Client Secret**
- **Tenant ID**
- API Permissions: `Sites.Read.All`, `Files.Read.All`
- Grant admin consent

---

## 8. Troubleshooting Guide

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pyodbc` import error | Missing ODBC driver | Install `msodbcsql18` in Dockerfile |
| SQL connection timeout | Firewall/network | Check `debug_tcp` endpoint |
| SharePoint 401 | Token expired | Check client secret & permissions |
| Railway 502 | Request timeout | Increase timeout or reduce `max_items` |
| CSV download 403 | Token expired | Regenerate within 60 minutes |
| Job stays "running" | Thread crashed | Check logs, restart container |

---

## 9. Security Checklist

- [ ] `API_TOKEN` is strong and rotated regularly
- [ ] `DOWNLOAD_TOKEN_SECRET` is >= 10 characters
- [ ] SQL Server uses least-privilege account (read-only)
- [ ] SharePoint app has minimal permissions
- [ ] Environment variables are NOT committed to Git
- [ ] HTTPS is enabled in production (`APP_BASE_URL`)
- [ ] SQL validation prevents injection (blocks all non-SELECT)

---

*Document generated for SQL-Analysis repository. Last updated: May 2026.*
