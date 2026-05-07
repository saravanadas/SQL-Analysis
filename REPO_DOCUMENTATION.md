# SQL-Analysis Repository Documentation
## Unified SQL MCP — Comprehensive Technical Guide

---

## 1. Project Overview

The **UnifiedDataMCP** is a Model Context Protocol (MCP) server built with FastAPI that acts as a secure bridge between:
- **On-premises Microsoft SQL Server** (via pyodbc + ODBC Driver 18)
- **SharePoint Online** (via Microsoft Graph API client credentials)
- **Railway-hosted PostgreSQL** (analytical staging database)

It exposes both **REST API endpoints** and **16 MCP tools** that allow AI agents to:
- Query SQL Server and return preview results
- Export SQL Server or PostgreSQL results to CSV with secure download links
- Stage data from SQL Server into Railway PostgreSQL (sync or async)
- Stage data from SharePoint (CSV/Excel/PDF) into Railway PostgreSQL
- Search, download, and extract text from SharePoint PDFs (with OCR fallback)
- Query the Railway analytical database directly

---

## 2. Architecture & Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web Framework | FastAPI 0.x | HTTP API layer + automatic OpenAPI docs |
| MCP Framework | FastMCP v2+ | Model Context Protocol tool registration |
| Database Engine | SQLAlchemy 2.x | Connection pooling & query execution |
| SQL Server Driver | pyodbc + ODBC Driver 18 | On-prem SQL Server connectivity |
| PostgreSQL Driver | psycopg2-binary | Railway DB connectivity |
| Data Processing | pandas | DataFrame manipulation & CSV export |
| SharePoint API | requests + Microsoft Graph API | File listing, download, metadata |
| PDF Processing | pypdf + PyMuPDF + pytesseract | Server-side PDF text extraction + OCR |
| Job Scheduling | APScheduler | Background cleanup (hourly) |
| Configuration | pydantic-settings | Environment-based config with validation |
| Security | HMAC-SHA256 | Secure download token generation & validation |
| Deployment | Docker + Railway | Containerized cloud deployment |
| CI/CD | GitHub Actions | Docker build + Railway smoke tests |
| Python Runtime | 3.11 (Docker) | Container base image |

---

## 3. Directory Structure

```
SQL-Analysis/
├── .env.example                    # Environment variables template
├── .gitignore                      # Git exclusions
├── Dockerfile                      # Python 3.11-slim + ODBC 18 + Tesseract OCR
├── Procfile                        # Railway/Heroku process definition
├── Project Structure.txt           # Repository layout reference
├── railway.toml                    # Railway deployment config
├── REPO_DOCUMENTATION.md           # This file
├── requirements.txt                # Python dependencies (17 packages)
├── TEST_PLAN.md                    # Three-phase test plan
│
├── src/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app, MCP init, middleware, debug endpoints
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py               # REST API endpoints
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py             # Pydantic-based configuration & validation
│   │   └── database.py             # Railway PostgreSQL engine factory
│   ├── engine/                     # (note: no __init__.py)
│   │   ├── background_jobs.py      # In-memory thread-safe job tracker (reference)
│   │   └── job_manager.py          # PostgreSQL-backed persistent job tracking
│   ├── services/
│   │   ├── __init__.py
│   │   ├── file_manager.py         # CSV generation, streaming write, temp cleanup
│   │   ├── sql_server_client.py    # SQL Server connection pool & chunked querying
│   │   ├── railway_db_client.py    # PostgreSQL data staging & tracking tables
│   │   └── sharepoint_client.py    # SharePoint Graph API integration
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── database_tools.py       # MCP tools: SQL/DB operations (6 tools)
│   │   └── sharepoint_tools.py     # MCP tools: SharePoint operations (10 tools)
│   └── utils/
│       ├── __init__.py
│       ├── security.py             # Token generation, query validation
│       ├── logger.py               # STDOUT logging for Railway
│       ├── retry.py                # Retry decorators (fixed + exponential backoff)
│       ├── data_validator.py       # DataFrame validation & cleaning
│       └── scheduler.py            # SharePoint ingestion scheduler (dormant)
│
├── tests/
│   ├── __init__.py
│   └── cli_tests.py               # 13-step smoke test suite
│
└── .github/
    └── workflows/
        └── ci.yml                  # Docker build + Railway smoke tests
```

---

## 4. Component Deep Dive

### 4.1 `main.py` — Application Entry Point

**Responsibilities:**
- Initializes the FastMCP instance (`UnifiedDataMCP`) and registers all 16 tools
- Creates the FastAPI app with async lifespan management
- Mounts the MCP HTTP app at `/mcp`
- Adds `TimeoutMiddleware` to prevent Railway 502 errors
- Runs background cleanup scheduler (hourly file cleanup)
- Provides debug endpoints for connectivity testing
- Graceful shutdown: cleans up SQL Server connection pool and Railway DB engine

**Key Classes:**

| Class | Purpose |
|-------|---------|
| `TimeoutMiddleware` | ASGI middleware that wraps each HTTP request in `asyncio.wait_for()`. Returns HTTP 504 if the request exceeds `settings.http_request_timeout_seconds` (default: 60s). Prevents Railway's proxy from returning a generic 502. |

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `create_mcp()` | Creates and configures the FastMCP instance, registers all DB and SP tools |
| `cleanup_job()` | Removes temp files older than 1 hour via `FileManager.cleanup_old_files()` |
| `lifespan()` | Async context manager — starts scheduler and MCP lifespan on startup; disposes SQL Server pool, Railway DB engine, and scheduler on shutdown |
| `health()` | Returns `{"status": "ok"}` (no auth) |
| `debug_tools()` | Lists all registered MCP tool names and count (Bearer auth) |
| `debug_tcp()` | Tests raw TCP connectivity and DNS resolution to SQL Server host (Bearer auth) |
| `debug_odbc()` | Tests full pyodbc connection to SQL Server, returns server name (Bearer auth) |
| `debug_sql()` | Executes `SELECT 1` via pyodbc against SQL Server (Bearer auth) |
| `debug_railway()` | Executes `SELECT 1` via SQLAlchemy against Railway PostgreSQL (Bearer auth) |
| `_check_debug_auth()` | Validates `Authorization: Bearer <API_TOKEN>` for debug endpoints |
| `main()` | Starts uvicorn on `0.0.0.0:$PORT` (default 8000) with `timeout_keep_alive=5` |

**Authentication:** Debug endpoints use `_check_debug_auth()` which reads `API_TOKEN` from `os.getenv("API_TOKEN")`. If `API_TOKEN` is not set, auth is effectively disabled.

---

### 4.2 `api/routes.py` — REST API Endpoints

**Router:** `APIRouter()` included at app root via `app.include_router(router)`.

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/health` | GET | Health check (also defined in `main.py`) | None |
| `/load-to-railway` | POST | Synchronous SQL Server → Railway staging | Bearer Token |
| `/load-to-railway/async` | POST | Queue async SQL Server → Railway staging job | Bearer Token |
| `/extract/sql` | POST | Start async SQL Server CSV extraction job | Bearer Token |
| `/extract/postgresql` | POST | Start async PostgreSQL CSV extraction job | Bearer Token |
| `/job/{job_id}` | GET | Get job status & result | **None** ⚠️ |
| `/jobs` | GET | List all background jobs | **None** ⚠️ |
| `/test-sharepoint` | GET | Test SharePoint OAuth token acquisition | Bearer Token |
| `/download/{file_id}` | GET | Download generated file | HMAC token (query param) |

> **⚠️ Known Issue:** `/job/{job_id}` and `/jobs` endpoints do not call `require_api_token()`. This allows unauthenticated access to job IDs and status information.

**Request Models:**
- `LoadRequest(BaseModel)`: Fields `query: str` and `table_name: str`
- `SQLRequest(BaseModel)`: Field `query: str`

**Background Worker Functions:**
- `process_sql_job(query)`: Executes SQL Server query, writes CSV, generates HMAC download token, returns `{file_id, download_url}`
- `process_postgresql_job(query)`: Same as above but against Railway PostgreSQL; calls `validate_query()` before execution
- `process_load_to_railway_job(query, table_name)`: Calls `load_sql_to_railway()` for async staging

**Auth Helper:**
- `require_api_token(authorization)`: Reads `API_TOKEN` from `os.getenv("API_TOKEN")` and compares against the `Authorization: Bearer <token>` header. Raises HTTP 401 if mismatch.

---

### 4.3 `config/settings.py` — Configuration Management

**Class:** `Settings(BaseSettings)` using `pydantic-settings`.

Loads configuration from environment variables or `.env` file. Singleton instance created at module level.

**SQL Server Settings:**

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `SQL_SERVER_HOST` | str | **Required** | Non-empty |
| `SQL_SERVER_PORT` | int | 1433 | — |
| `SQL_SERVER_DB` | str | **Required** | Non-empty |
| `SQL_SERVER_USER` | str | **Required** | Non-empty |
| `SQL_SERVER_PASSWORD` | str | **Required** | — |
| `DB_DRIVER` | str | `"ODBC Driver 18 for SQL Server"` | — |

**Railway PostgreSQL Settings:**

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `RAILWAY_DB_URL` | str | **Required** | Must start with `postgresql://` |

**SharePoint Settings:**

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `SP_TENANT_ID` | str | **Required** | Non-empty |
| `SP_CLIENT_ID` | str | **Required** | Non-empty |
| `SP_CLIENT_SECRET` | str | **Required** | Non-empty |
| `SP_SITE_ID` | str | **Required** | Non-empty |
| `SP_DRIVE_ID` | str | **Required** | — |

**Application Settings:**

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `LOG_LEVEL` | str | `"INFO"` | — |
| `OUTPUT_DIR` | str | `"/app/output_files"` | Non-empty |
| `APP_BASE_URL` | str | `"http://localhost:8000"` | — |

**Security Settings:**

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `DOWNLOAD_TOKEN_SECRET` | str | **Required** | Min 10 characters |

**Timeout & Sizing Settings:**

| Variable | Type | Default | Validation |
|----------|------|---------|------------|
| `HTTP_REQUEST_TIMEOUT_SECONDS` | int | 60 | Non-negative |
| `SQL_SERVER_CONNECT_TIMEOUT_SECONDS` | int | 10 | Non-negative |
| `SQL_SERVER_LOGIN_TIMEOUT_SECONDS` | int | 10 | Non-negative |
| `SQL_SERVER_POOL_TIMEOUT_SECONDS` | int | 30 | Non-negative |
| `SQL_SERVER_PREVIEW_TIMEOUT_SECONDS` | int | 30 | Non-negative |
| `SQL_SERVER_EXTRACT_TIMEOUT_SECONDS` | int | 300 | Non-negative |
| `SQL_SERVER_FORCE_ABORT_SECONDS` | int | 0 | Non-negative; 0 disables hard abort |
| `RAILWAY_CONNECT_TIMEOUT_SECONDS` | int | 10 | Non-negative |
| `RAILWAY_QUERY_STATEMENT_TIMEOUT_MS` | int | 30000 | Non-negative |
| `RAILWAY_EXPORT_STATEMENT_TIMEOUT_MS` | int | 0 | Non-negative; 0 disables timeout |
| `RAILWAY_INSERT_CHUNKSIZE` | int | 500 | Non-negative |

> **Note:** `API_TOKEN` is **not** declared in the `Settings` class. It is accessed directly via `os.getenv("API_TOKEN")` in `routes.py` and `main.py`. This means Pydantic validation does not apply to it.

> **⚠️ Known Issue:** Line 131 contains `print("Loaded Railway DB URL:", settings.railway_db_url[:30], "...")` which leaks the first 30 characters of the Railway DB URL to stdout on every startup.

---

### 4.4 `config/database.py` — Railway Engine Factory

**Function:** `get_engine()`

Creates a SQLAlchemy engine using `settings.railway_db_url` with `pool_pre_ping=True`. Used by `JobManager` for persistent job storage.

---

### 4.5 `engine/job_manager.py` — Persistent Background Jobs

**Class:** `JobManager`

Uses PostgreSQL `jobs` table for persistent job tracking and Python `threading.Thread` for background execution.

| Method | Purpose |
|--------|---------|
| `__init__()` | Gets engine from `get_engine()`, calls `_ensure_schema()` |
| `_ensure_schema()` | Auto-creates `jobs` table with `CREATE TABLE IF NOT EXISTS` and adds missing columns with `ALTER TABLE ADD COLUMN IF NOT EXISTS` |
| `create_job(func, *args)` | Inserts job record with `status='running'`, spawns daemon thread, returns UUID job_id |
| `run_job(job_id, func, args)` | Executes function, updates DB with `status='completed'` + JSON result or `status='failed'` + error message |
| `get_job(job_id)` | Retrieves job from PostgreSQL. Returns `{"error": "Job not found"}` if no row matches |
| `list_jobs()` | Returns all jobs ordered by `created_date DESC` |

**Job States:** `running` → `completed` | `failed`

**Schema (auto-created):**
```sql
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created_date TIMESTAMPTZ DEFAULT NOW()
)
```

---

### 4.6 `engine/background_jobs.py` — In-Memory Job Tracker (Reference)

**Class:** `BackgroundJobManager`

A thread-safe, in-memory job tracker using `threading.Lock` and a dictionary.

> **Note:** This class is **not currently used** by any route or tool. The API routes and MCP tools use `JobManager` (PostgreSQL-backed) from `job_manager.py` instead. `BackgroundJobManager` is retained in the codebase for reference.

| Method | Purpose |
|--------|---------|
| `submit_job(job_id, func, *args, **kwargs)` | Creates in-memory record, spawns thread |
| `get_job(job_id)` | Returns job dict (thread-safe copy) |
| `list_jobs()` | Returns list of all job dicts |

**Job States:** `pending` → `running` → `completed` | `failed`

---

### 4.7 `services/file_manager.py` — File Operations

**Class:** `FileManager`

Handles temp file generation, cleanup, and secure download preparation. Creates `output_dir` on init if it doesn't exist.

| Method | Purpose |
|--------|---------|
| `generate_csv_from_dataframe(df, base_filename)` | Creates timestamped CSV from DataFrame |
| `get_file_content_base64(filepath)` | Converts file to base64 for MCP transmission |
| `generate_file_id()` | Returns UUID string for unique file identification |
| `get_file_path(file_id, extension)` | Builds output path with given extension (default: `csv`) |
| `get_file(file_id)` | Searches output_dir for any file starting with file_id |
| `cleanup_old_files(hours)` | Deletes files older than N hours from output_dir |
| `write_csv_stream(file_path, generator)` | Memory-efficient streaming CSV writer — handles DataFrame chunks, schema mismatches |

---

### 4.8 `services/sql_server_client.py` — SQL Server Client

**Classes:** `ConnectionPool` and `SQLServerClient`

#### `ConnectionPool`

A queue-based, thread-safe connection pool wrapper around SQLAlchemy connections.

| Method | Purpose |
|--------|---------|
| `get()` | Returns a pooled connection or creates new (up to `maxsize=10`). Blocks with timeout if pool exhausted. |
| `put(conn)` | Returns connection to pool. Discards if closed or pool full. |
| `discard(conn)` | Closes connection and decrements counter |
| `close_all()` | Drains and closes all pooled connections |

#### `SQLServerClient`

Connects to on-premises SQL Server via pyodbc with configurable timeouts.

| Method | Purpose |
|--------|---------|
| `execute_query_to_dataframe(query, chunksize, query_timeout_seconds, force_abort_seconds)` | Streaming query execution with operation-specific timeout profile. Validates query first via `validate_query()`. Returns iterator of DataFrames. |
| `close()` | Closes pool and disposes engine |

**Connection Features:**
- Builds ODBC connection string from Settings fields
- SQLAlchemy engine: `pool_size=10`, `max_overflow=20`, `pool_recycle=1800`, `pool_pre_ping=True`
- Custom `ConnectionPool` wraps SQLAlchemy connections for explicit get/put/discard lifecycle
- Optional hard-abort timer: if `force_abort_seconds > 0`, a `threading.Timer` closes the connection after N seconds
- Closed or aborted connections are discarded instead of returned to the pool
- `@retry` decorator: 3 attempts, 3s delay

---

### 4.9 `services/railway_db_client.py` — PostgreSQL Client

**Class:** `RailwayDBClient`

Manages the analytical staging database on Railway. Verifies connectivity on init with `SELECT 1`.

**Data Staging Methods:**

| Method | Purpose |
|--------|---------|
| `stage_dataframe(df, table_name, if_exists)` | Loads DataFrame to PostgreSQL via `df.to_sql()` |
| `insert_dataframe_chunked(df, table_name, mode)` | Chunk-safe insert with `replace` or `append` mode |
| `bulk_insert(df, table_name)` | Optimized append-mode bulk insert |

**Query Methods:**

| Method | Purpose |
|--------|---------|
| `execute_query(query, statement_timeout_ms)` | Bounded analytical SELECT, returns DataFrame. Uses PostgreSQL `SET statement_timeout`. |
| `execute_query_to_dataframe(query, chunksize, statement_timeout_ms)` | Streaming SELECT for CSV exports, yields DataFrame chunks |

**File Tracking Methods:**

| Method | Purpose |
|--------|---------|
| `ensure_tracking_table()` | Creates `mcp_file_tracking` table |
| `is_file_processed(file_name)` | Checks if file already ingested |
| `mark_file_processed(file_name)` | Marks file as processed (with ON CONFLICT DO NOTHING) |

**PDF/Invoice Methods:**

| Method | Purpose |
|--------|---------|
| `ensure_pdf_text_table(table_name)` | Creates table for PDF page text |
| `ensure_invoice_file_table(table_name)` | Creates table for invoice PDF metadata |
| `get_invoice_file_record(file_id, table_name)` | Retrieves existing PDF metadata record |
| `upsert_invoice_file_record(record, table_name)` | Insert/update PDF metadata (ON CONFLICT DO UPDATE) |
| `store_pdf_text_rows(rows, table_name)` | Deletes existing rows for file_id, then inserts new page text rows |

**Connection Features:**
- SQLAlchemy engine: `pool_size=10`, `max_overflow=20`, `pool_recycle=1800`, `pool_pre_ping=True`
- Uses PostgreSQL `SET statement_timeout` per query for bounded execution
- All table names validated via `_validate_table_name()` regex: `[A-Za-z_][A-Za-z0-9_]*`
- `@retry` decorator on all data methods: 3 attempts, 2s delay

---

### 4.10 `services/sharepoint_client.py` — SharePoint Client

**Class:** `SharePointClient`

Integrates with SharePoint via Microsoft Graph API using OAuth2 client credentials flow.

| Method | Purpose |
|--------|---------|
| `_get_access_token()` | Acquires OAuth2 token from Azure AD (timeout: 10s) |
| `_headers()` | Returns Bearer token headers (auto-refresh if token is None) |
| `list_files(folder_path, max_items)` | Lists files with pagination. Default limit 200. Auto-refreshes on 401. |
| `list_files_recursive(folder_path, max_items)` | Recursively walks folders, adds `_path` key to each item. Default limit 1000. |
| `download_file(download_url)` | Downloads file bytes (timeout: 15s). Auto-refreshes on 401. |
| `get_file_metadata(file_id)` | Fetches file metadata & download URL (timeout: 10s). Auto-refreshes on 401. |

---

### 4.11 `tools/database_tools.py` — MCP Database Tools

**6 Tools Registered:**

| Tool Name | Purpose | Parameters |
|-----------|---------|------------|
| `query_sql_server` | Execute bounded preview SELECT on SQL Server, returns markdown table (first 10 rows) | `query: str` |
| `extract_sql_to_csv` | Export SQL Server SELECT results to CSV with secure download link | `query: str` |
| `stage_sql_to_railway` | Synchronous SQL Server → Railway staging (for small jobs) | `query: str`, `target_table: str` |
| `stage_sql_to_railway_async` | Queue long-running SQL Server → Railway staging job, returns job ID | `query: str`, `target_table: str` |
| `query_analytical_db` | Query Railway PostgreSQL, returns markdown preview (first 10 rows) | `query: str` |
| `extract_analytical_to_csv` | Export PostgreSQL analytical results to CSV with secure download link | `query: str` |

**Shared Function:**
- `load_sql_to_railway(query, table_name, query_timeout_seconds, chunksize)`: Core pipeline logic used by both MCP tools and REST API. Validates query, streams SQL Server results in chunks, inserts into Railway PostgreSQL (first chunk replaces, subsequent chunks append).

**Export Routing Rule:** Use `extract_sql_to_csv` for simple SQL Server exports. For complex joins, grouped aggregations, or any SQL Server export that may exceed the extract timeout, use `stage_sql_to_railway_async` first, then export the staged PostgreSQL table with `extract_analytical_to_csv`.

---

### 4.12 `tools/sharepoint_tools.py` — MCP SharePoint Tools

**10 Tools Registered:**

| Tool Name | Purpose | Key Parameters |
|-----------|---------|----------------|
| `ingest_sharepoint_invoice_pdfs_to_railway` | Bulk PDF ingestion with deduplication & change detection | `folder_path`, `batch_number`, `max_files`, `force_reprocess`, `pdf_text_table`, `file_table` |
| `ingest_invoice_pdfs` | Short alias for above using default tables | `folder_path`, `batch_number`, `max_files`, `force_reprocess` |
| `search_sharepoint_pdfs_recursive` | Find invoice PDFs recursively (excludes `*report.pdf`) | `folder_path`, `batch_number`, `max_items` |
| `extract_sharepoint_pdf_text` | Download & extract PDF text with OCR fallback | `file_id`, `file_name`, `max_preview_chars` |
| `stage_sharepoint_pdf_text_to_railway` | Extract & store PDF page text in PostgreSQL | `file_id`, `file_name`, `sharepoint_path`, `table_name` |
| `stage_invoice_lines_to_railway` | Store parsed invoice line data in PostgreSQL | `rows: list[dict]`, `table_name`, `mode` |
| `list_sharepoint_files` | List files in SharePoint folder | `folder_path` |
| `download_sharepoint_file` | Download single file with secure download link | `file_id`, `file_name` |
| `download_sharepoint_folder` | Download all files in folder with secure links | `folder_path` |
| `sharepoint_to_railway` | CSV/Excel → PostgreSQL ingestion pipeline with file tracking | `folder_path`, `table_name` |

**PDF Processing Pipeline:**
1. Download PDF from SharePoint via Graph API
2. Extract text per page using `pypdf`
3. If page has <50 chars of text and contains images, fall back to OCR via `PyMuPDF` + `pytesseract`
4. Sanitize text (remove null bytes, control characters)
5. Store in PostgreSQL with `(file_id, page_number)` primary key

**Invoice Deduplication:** `ingest_sharepoint_invoice_pdfs_to_railway` checks existing records by `file_id`, comparing `last_modified`, `file_size`, and `extraction_status`. Files that haven't changed are skipped unless `force_reprocess=True`.

---

### 4.13 `utils/security.py` — Security Utilities

| Function | Purpose |
|----------|---------|
| `generate_token(file_name, expiry_minutes=60)` | HMAC-SHA256 signed download token. Returns `"expiry:signature"` string. |
| `validate_token(file_name, token)` | Validates token signature & expiry. Uses `hmac.compare_digest()` for constant-time comparison. |
| `validate_query(query)` | SQL injection prevention — SELECT-only enforcement. |

**Query Validation Rules:**
1. Query must not be empty or whitespace-only
2. Single-line (`--`) and multi-line (`/* */`) comments are stripped before validation
3. Must start with `SELECT` (case-insensitive)
4. Blocks forbidden keywords: `DROP`, `DELETE`, `TRUNCATE`, `ALTER`, `UPDATE`, `INSERT`, `EXEC`, `EXECUTE`, `MERGE`
5. No multiple statements (`;` forbidden)

---

### 4.14 `utils/logger.py` — Logging

**Function:** `setup_logger(name)`

- STDOUT output for Railway log aggregation
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- Level controlled by `settings.log_level` (default: INFO)
- Singleton pattern (prevents duplicate handlers)

---

### 4.15 `utils/retry.py` — Retry Decorators

Three retry mechanisms, from newest to oldest:

| Function | Strategy | Used By |
|----------|----------|---------|
| `retry_with_backoff(max_retries, base_delay, max_delay, exceptions)` | Jittered exponential backoff. `delay = min(base_delay * 2^attempt + random(0,1), max_delay)` | Not directly referenced yet |
| `network_retry` | Pre-configured `retry_with_backoff` (3 retries, 1s base, 15s max) | Not directly referenced yet |
| `retry(max_attempts=3, delay=2)` | Simple fixed-delay retry. Backward-compatible alias. | `SQLServerClient`, `RailwayDBClient` |

---

### 4.16 `utils/data_validator.py` — Data Cleaning

**Function:** `validate_dataframe(df)`

- Removes empty rows (`dropna(how="all")`)
- Trims column names (strips whitespace)
- Removes duplicate rows

Used by the `sharepoint_to_railway` tool when ingesting CSV/Excel files.

---

### 4.17 `utils/scheduler.py` — Background Scheduling (Dormant)

**Function:** `start_scheduler()`

Starts APScheduler with a daily SharePoint ingestion job targeting `Finance/Reports → finance_reports` table.

> **⚠️ Known Issue:** Line 2 imports `sharepoint_to_railway` directly from `src.tools.sharepoint_tools`. However, `sharepoint_to_railway` is a nested function registered as an MCP tool inside `register_sharepoint_tools()`, not a module-level function. This import would raise `ImportError` if `start_scheduler()` were ever called. This module is currently dormant — `main.py` uses its own `BackgroundScheduler` instance for the cleanup job instead.

---

## 5. Environment Variables Quick Reference

Create a `.env` file (copy from `.env.example`) with:

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

# Application & Security
API_TOKEN=your-secure-api-token
DOWNLOAD_TOKEN_SECRET=your-secret-for-download-tokens-min-10-chars
LOG_LEVEL=INFO
OUTPUT_DIR=/app/output_files
APP_BASE_URL=https://your-app.railway.app

# Timeout & Sizing (all optional — shown with defaults)
HTTP_REQUEST_TIMEOUT_SECONDS=60
SQL_SERVER_CONNECT_TIMEOUT_SECONDS=10
SQL_SERVER_LOGIN_TIMEOUT_SECONDS=10
SQL_SERVER_POOL_TIMEOUT_SECONDS=30
SQL_SERVER_PREVIEW_TIMEOUT_SECONDS=30
SQL_SERVER_EXTRACT_TIMEOUT_SECONDS=300
SQL_SERVER_FORCE_ABORT_SECONDS=0
RAILWAY_CONNECT_TIMEOUT_SECONDS=10
RAILWAY_QUERY_STATEMENT_TIMEOUT_MS=30000
RAILWAY_EXPORT_STATEMENT_TIMEOUT_MS=0
RAILWAY_INSERT_CHUNKSIZE=500
```

---

## 6. Smoke Test Plan

### 6.1 Prerequisites

1. Docker installed locally (or Python 3.11+)
2. All environment variables configured in `.env`
3. SQL Server accessible from test machine
4. SharePoint app registration with client credentials
5. Railway PostgreSQL accessible (for job tracking and staging)

### 6.2 Test 1: Application Startup

```bash
# Build and run
docker build -t unified-mcp .
docker run -p 8000:8000 --env-file .env unified-mcp

# Or locally:
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Expected:** Server starts without errors, logs show "MCP mounted successfully at /mcp" and "Scheduler started".

### 6.3 Test 2: Health Check

```bash
curl http://localhost:8000/health
```

**Expected:** `{"status": "ok"}`

### 6.4 Test 3: Debug Tools List

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
```

**Expected:** JSON with `tool_count` = 16 and full list of tool names.

### 6.5 Test 4: SQL Server Connectivity (Debug TCP)

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tcp
```

**Expected:** `{"ok": true, ...}` with resolved IP addresses.

### 6.6 Test 5: SQL Server ODBC Connection

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/odbc
```

**Expected:** `{"ok": true, "server": "YOUR_SERVER_NAME"}`

### 6.7 Test 6: SQL Server Query

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/sql
```

**Expected:** `{"ok": true, "value": 1}`

### 6.8 Test 7: REST API — Extract SQL to CSV

```bash
curl -X POST http://localhost:8000/extract/sql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT 1 AS test_column"}'
```

**Expected:** `{"job_id": "uuid", "status": "started"}`

### 6.9 Test 8: Job Status Check

```bash
curl http://localhost:8000/job/{job_id_from_test_7}
```

**Expected:** After completion: `{"job_id": "...", "status": "completed", "result": {...}}`

### 6.10 Test 9: File Download

Use the download URL from job result:
```bash
curl "http://localhost:8000/download/{file_id}?token={token}"
```

**Expected:** CSV file download with correct data.

### 6.11 Test 10: SharePoint Token Test

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/test-sharepoint
```

**Expected:** `{"status": "success", "message": "SharePoint auth working"}`

### 6.12 Test 11: Synchronous SQL → Railway Pipeline

```bash
curl -X POST http://localhost:8000/load-to-railway \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{
    "query": "SELECT 1 AS col_a, 2 AS col_b",
    "table_name": "smoke_test_staging"
  }'
```

**Expected:** `{"status": "success", "rows_loaded": 1, ...}`

### 6.13 Test 12: Async SQL → Railway Pipeline

```bash
curl -X POST http://localhost:8000/load-to-railway/async \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{
    "query": "SELECT 1 AS col_a, 2 AS col_b",
    "table_name": "smoke_test_staging_async"
  }'
```

**Expected:** `{"job_id": "uuid", "status": "started", "status_url": "/job/{job_id}"}`. Poll `/job/{job_id}` until `completed` or `failed`.

### 6.14 Test 13: PostgreSQL CSV Export

```bash
curl -X POST http://localhost:8000/extract/postgresql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"query": "SELECT * FROM smoke_test_staging"}'
```

**Expected:** `{"job_id": "uuid", "status": "started"}`. Poll `/job/{job_id}` for result with download URL.

### 6.15 Test 14: Railway DB Connectivity

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/railway
```

**Expected:** `{"ok": true, "value": 1, ...}`

### 6.16 Test 15: MCP Tool — query_sql_server

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

### 6.17 Test 16: MCP Tool — list_sharepoint_files

```json
{
  "tool": "list_sharepoint_files",
  "arguments": {
    "folder_path": "Documents"
  }
}
```

**Expected:** List of files and folders with IDs.

### 6.18 Test 17: SharePoint → Railway Pipeline

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

The Dockerfile installs:
- Python 3.11 (slim-bookworm)
- ODBC Driver 18 for SQL Server (`msodbcsql18`)
- Tesseract OCR (`tesseract-ocr`) for PDF image processing
- All Python dependencies from `requirements.txt`

### Railway Deployment
1. Push to GitHub `main` branch
2. Railway auto-deploys via `railway.toml` (Dockerfile builder)
3. Set all environment variables in Railway dashboard
4. Restart policy: `ON_FAILURE` with max 3 retries
5. Start command: `python -m src.main`

### Procfile (Heroku/Railway fallback)
```
web: uvicorn src.main:app --host 0.0.0.0 --port $PORT
```

### SharePoint App Registration Requirements
- **Application (client) ID** — Azure AD app registration
- **Client Secret** — Created in Certificates & secrets
- **Tenant ID** — Azure AD tenant
- API Permissions: `Sites.Read.All`, `Files.Read.All` (application type)
- Grant admin consent

---

## 8. Troubleshooting Guide

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pyodbc` import error | Missing ODBC driver | Install `msodbcsql18` in Dockerfile (already included) |
| SQL connection timeout | Firewall/network | Check `debug_tcp` endpoint; allowlist Railway IPs |
| SharePoint 401 | Token expired or permissions | Renew client secret; verify `Sites.Read.All` permission |
| Railway 502 | Sync request exceeded proxy timeout | Use `/load-to-railway/async` or `stage_sql_to_railway_async`; tune `HTTP_REQUEST_TIMEOUT_SECONDS` |
| Railway 504 | `TimeoutMiddleware` triggered | Query is too slow; use async endpoint or narrow the query |
| SQL Server CSV export times out | Extract exceeds 300s default | Stage with `stage_sql_to_railway_async`, then export with `extract_analytical_to_csv` |
| PostgreSQL preview query times out | `RAILWAY_QUERY_STATEMENT_TIMEOUT_MS` budget exceeded | Narrow the query or use CSV export for full data |
| CSV download 403 | HMAC token invalid or expired | Regenerate within 60 minutes |
| Job stays "running" | Background thread crashed | Check logs, restart container |
| `Settings` validation error on startup | Missing required env var | Check `.env` file against `.env.example` |
| Local SQL Server: wrong driver | `DB_DRIVER` defaults to Driver 18 | Set `DB_DRIVER=ODBC Driver 17 for SQL Server` in `.env` if Driver 17 is installed locally |
| Local Railway DB connection fails | `RAILWAY_DB_URL` uses internal hostname | Use the public Railway DB URL for local development, or accept that Railway DB tests will fail locally |

---

## 9. Security Checklist

- [ ] `API_TOKEN` is strong and rotated regularly
- [ ] `DOWNLOAD_TOKEN_SECRET` is >= 10 characters and different from `API_TOKEN`
- [ ] SQL Server account uses least-privilege (read-only)
- [ ] SharePoint app has minimal permissions (`Sites.Read.All`, `Files.Read.All`)
- [ ] `.env` file is NOT committed to Git (verified in `.gitignore`)
- [ ] HTTPS is enabled in production (`APP_BASE_URL` set to `https://`)
- [ ] SQL validation prevents injection (blocks all non-SELECT via `validate_query()`)
- [ ] Download tokens use HMAC-SHA256 with constant-time comparison

---

## 10. Continuous Integration & Test Strategy

### 10.1 Three-Phase Testing Overview

| Phase | What It Tests | Where It Runs | When | If It Fails |
|-------|---------------|---------------|------|-------------|
| 1. Local Smoke Tests | Code correctness, endpoint responses, auth | Your machine (Docker or venv) | Before every push | Fix code locally. Do NOT push. |
| 2. GitHub Actions CI | Docker build, clean-environment validation | GitHub CI runner (Ubuntu) | Every push to `main` | Check Dockerfile for OS-specific deps |
| 3. Railway Smoke Tests | Production networking, DB connectivity, cloud credentials | Live Railway deployment | After CI passes on `main` | Check Railway env vars, firewall rules |

### 10.2 Automated Test Runner

The `tests/cli_tests.py` script runs 13 sequential smoke tests:

| Step | Test | Endpoint |
|------|------|----------|
| 1 | Health Check | `GET /health` |
| 2 | Debug Tools List | `GET /debug/tools` |
| 3 | SQL Server TCP | `GET /debug/tcp` |
| 4 | SQL Server ODBC | `GET /debug/odbc` |
| 5 | SQL Server Query | `GET /debug/sql` |
| 6 | Extract SQL to CSV | `POST /extract/sql` |
| 7 | Job Poll (extract) | `GET /job/{job_id}` |
| 8 | File Download | `GET /download/{file_id}?token=...` |
| 9 | SharePoint Token | `GET /test-sharepoint` |
| 10 | Sync SQL → Railway | `POST /load-to-railway` |
| 11 | Async SQL → Railway | `POST /load-to-railway/async` |
| 12 | Job Poll (async) | `GET /job/{job_id}` |
| 13 | Railway DB Connectivity | `GET /debug/railway` |

```bash
python tests/cli_tests.py --base-url http://localhost:8000 --api-token YOUR_TOKEN
```

### 10.3 GitHub Actions Workflow

The CI workflow (`.github/workflows/ci.yml`) runs on every push to `main`:

1. **Build job:** Builds the Docker image on Ubuntu
2. **Railway smoke job:** Waits 60s for Railway deployment, then runs health check, tools list, SharePoint auth, Railway DB connectivity, SQL Server connectivity, and extract SQL tests via `curl`

### 10.4 Required GitHub Repository Secrets

| Secret | Purpose |
|--------|---------|
| `API_TOKEN` | Production API token for authenticated smoke test endpoints |

> **Note:** The CI workflow currently hardcodes `RAILWAY_URL` instead of using a `RAILWAY_APP_URL` secret. This should be updated to `${{ secrets.RAILWAY_APP_URL }}`.

### 10.5 Full Documentation

For complete step-by-step test instructions, decision gates, and troubleshooting, see **`TEST_PLAN.md`**.

---

## 11. Known Issues & Technical Debt

| # | Issue | Severity | Location | Notes |
|---|-------|----------|----------|-------|
| 1 | `/jobs` endpoint has no authentication | High | `routes.py:288` | Allows unauthenticated access to job listing |
| 2 | `/job/{job_id}` endpoint has no authentication | Medium | `routes.py:222` | Allows unauthenticated job status lookup |
| 3 | `/extract/sql` does not call `validate_query()` at route layer | Medium | `routes.py:134` | Dangerous queries get HTTP 200 + job_id; worker-layer validator blocks actual execution |
| 4 | `settings.py` leaks partial Railway DB URL to stdout | Low | `settings.py:131` | `print()` statement should be removed or logged at DEBUG level |
| 5 | `scheduler.py` has incorrect import | Low | `scheduler.py:2` | Imports MCP tool function directly; would raise ImportError if called |
| 6 | `engine/` directory has no `__init__.py` | Low | `src/engine/` | Works due to direct imports but technically not a proper Python package |
| 7 | `API_TOKEN` not in `Settings` class | Low | `routes.py:23`, `main.py:133` | Accessed via `os.getenv()` — bypasses Pydantic validation |
| 8 | CI workflow hardcodes Railway URL | Low | `ci.yml:24` | Should use `${{ secrets.RAILWAY_APP_URL }}` |
| 9 | `background_jobs.py` is unused | Info | `engine/background_jobs.py` | In-memory job tracker retained for reference; routes use PostgreSQL-backed `JobManager` |

---

*Document updated for SQL-Analysis repository. Last updated: May 2026.*
