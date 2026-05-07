# UnifiedDataMCP

**A FastAPI + MCP service that bridges on-premises SQL Server, SharePoint Online, and Railway PostgreSQL — exposing 16 AI-ready tools for data extraction, transformation, and staging.**

---

## What It Does

UnifiedDataMCP is a Model Context Protocol (MCP) server built on FastAPI that connects three enterprise data sources into a single API layer:

```
┌─────────────────────┐      ┌──────────────────────────┐      ┌─────────────────────┐
│  On-Prem SQL Server │─────▶│                          │─────▶│  Railway PostgreSQL  │
│  (pyodbc/ODBC 18)   │      │     UnifiedDataMCP       │      │  (Analytical Store)  │
└─────────────────────┘      │                          │      └─────────────────────┘
                             │  FastAPI + FastMCP        │
┌─────────────────────┐      │  16 MCP Tools            │      ┌─────────────────────┐
│  SharePoint Online  │─────▶│  REST API + Async Jobs   │─────▶│  CSV File Downloads  │
│  (Microsoft Graph)  │      │  HMAC-Signed Downloads   │      │  (Secure Tokens)     │
└─────────────────────┘      └──────────────────────────┘      └─────────────────────┘
```

**Use cases:**
- AI agents (Claude, GPT, etc.) query on-prem SQL Server databases via MCP tools
- Extract SQL query results to downloadable CSV files with secure HMAC-signed URLs
- Stage SQL Server data into Railway PostgreSQL for analytical workloads
- Ingest SharePoint PDF invoices, extract text, and load into the analytical database
- Search, list, and download files from SharePoint document libraries

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Web Framework** | FastAPI 0.115+ with Uvicorn |
| **MCP Server** | FastMCP (Model Context Protocol) |
| **SQL Server** | pyodbc + ODBC Driver 18 for SQL Server |
| **PostgreSQL** | SQLAlchemy 2.x + psycopg2 (Railway-hosted) |
| **SharePoint** | Microsoft Graph API (OAuth2 client credentials) |
| **PDF Processing** | pdfplumber (text extraction from invoices) |
| **Background Jobs** | PostgreSQL-backed job manager with threading |
| **Scheduling** | APScheduler (hourly file cleanup) |
| **Deployment** | Docker + Railway (auto-deploy from `main`) |

---

## Quick Start

### Prerequisites

- Python 3.11+ (3.13 supported)
- Docker (recommended for production-like environment)
- ODBC Driver 18 for SQL Server (included in Docker image)
- Access credentials for SQL Server, SharePoint, and Railway PostgreSQL

### 1. Clone and Configure

```bash
git clone https://github.com/saravanadas/SQL-Analysis.git
cd SQL-Analysis
cp .env.example .env
# Edit .env with your actual credentials
```

### 2a. Run with Docker (Recommended)

```bash
docker build -t unified-mcp .
docker run -p 8000:8000 --env-file .env unified-mcp
```

### 2b. Run Locally (Development)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 3. Verify

```bash
curl http://localhost:8000/health
# {"status": "ok"}

curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/debug/tools
# {"tool_count": 16, "tools": [...]}
```

---

## API Endpoints

All endpoints except `/health` require a Bearer token via the `Authorization` header.

### Health & Debug

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check — returns `{"status": "ok"}` |
| GET | `/debug/tools` | Bearer | List all registered MCP tools with count |
| GET | `/debug/tcp` | Bearer | Test TCP connectivity to SQL Server (DNS + socket) |
| GET | `/debug/odbc` | Bearer | Test ODBC driver connection to SQL Server |
| GET | `/debug/sql` | Bearer | Execute `SELECT 1` roundtrip on SQL Server |
| GET | `/debug/railway` | Bearer | Execute `SELECT 1` roundtrip on Railway PostgreSQL |

### Data Extraction & Staging

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/extract/sql` | Bearer | Start async SQL Server extraction → CSV (returns job_id) |
| POST | `/extract/postgresql` | Bearer | Start async PostgreSQL extraction → CSV (returns job_id) |
| POST | `/load-to-railway` | Bearer | Sync: SQL Server query → Railway PostgreSQL table |
| POST | `/load-to-railway/async` | Bearer | Async: SQL Server query → Railway PostgreSQL table (returns job_id) |

### Jobs & Downloads

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/job/{job_id}` | None | Poll async job status and result |
| GET | `/jobs` | None | List all background jobs |
| GET | `/download/{file_id}` | HMAC token | Download generated CSV file (requires `?token=` query param) |

### SharePoint

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/test-sharepoint` | Bearer | Test SharePoint OAuth token acquisition |

### MCP

| Path | Description |
|------|-------------|
| `/mcp` | FastMCP endpoint (requires MCP transport headers — use an MCP client) |

---

## MCP Tools (16 Total)

These tools are accessible via any MCP-compatible client (e.g., Claude Desktop) connected to the `/mcp` endpoint.

### Database Tools (6)

| Tool | Description |
|------|-------------|
| `query_sql_server` | Execute a read-only SQL query and return results as a Markdown table |
| `extract_sql_to_csv` | Extract SQL query results to a downloadable CSV file |
| `stage_sql_to_railway` | Execute SQL Server query and load results into Railway PostgreSQL |
| `stage_sql_to_railway_async` | Async version — returns a job_id for polling |
| `query_analytical_db` | Query the Railway PostgreSQL analytical database |
| `extract_analytical_to_csv` | Extract PostgreSQL query results to a downloadable CSV file |

### SharePoint Tools (10)

| Tool | Description |
|------|-------------|
| `list_sharepoint_files` | List files and folders in a SharePoint document library |
| `download_sharepoint_file` | Download a single file from SharePoint by file ID |
| `download_sharepoint_folder` | Download all files in a SharePoint folder |
| `search_sharepoint_pdfs_recursive` | Recursively search for PDF files across SharePoint folders |
| `extract_sharepoint_pdf_text` | Extract text content from a SharePoint PDF |
| `stage_sharepoint_pdf_text_to_railway` | Extract PDF text and load into Railway PostgreSQL |
| `ingest_sharepoint_invoice_pdfs_to_railway` | Batch: find, extract, and stage invoice PDFs to Railway |
| `ingest_invoice_pdfs` | Ingest invoice PDFs with line-item parsing |
| `stage_invoice_lines_to_railway` | Stage parsed invoice line items to Railway PostgreSQL |
| `sharepoint_to_railway` | Generic SharePoint-to-Railway pipeline |

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

### Required

| Variable | Description |
|----------|-------------|
| `SQL_SERVER_HOST` | On-prem SQL Server hostname or IP |
| `SQL_SERVER_DB` | Database name |
| `SQL_SERVER_USER` | SQL Server username |
| `SQL_SERVER_PASSWORD` | SQL Server password |
| `RAILWAY_DB_URL` | PostgreSQL connection string (e.g., `postgresql://user:pass@host:5432/db`) |
| `SP_TENANT_ID` | Microsoft Entra tenant ID |
| `SP_CLIENT_ID` | SharePoint app registration client ID |
| `SP_CLIENT_SECRET` | SharePoint app registration client secret |
| `SP_SITE_ID` | SharePoint site ID |
| `SP_DRIVE_ID` | SharePoint document library drive ID |
| `API_TOKEN` | Bearer token for REST API authentication |
| `DOWNLOAD_TOKEN_SECRET` | HMAC-SHA256 secret for download URLs (min 10 characters) |

### Optional (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `SQL_SERVER_PORT` | `1433` | SQL Server port |
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` | ODBC driver name |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `OUTPUT_DIR` | `/app/output_files` | Directory for generated CSV files |
| `APP_BASE_URL` | `http://localhost:8000` | Base URL for download links |
| `HTTP_REQUEST_TIMEOUT_SECONDS` | `60` | Request timeout budget |

See [REPO_DOCUMENTATION.md](REPO_DOCUMENTATION.md) for the full list of timeout and performance tuning variables.

---

## Deployment

### Railway (Production)

The app is configured for Railway deployment via:
- **`Dockerfile`** — Multi-stage build with ODBC Driver 18, Python dependencies
- **`railway.toml`** — Build and deploy configuration
- **`Procfile`** — `web: uvicorn src.main:app --host 0.0.0.0 --port $PORT`

Railway auto-deploys from the `main` branch. Set all environment variables in the Railway dashboard.

### CI/CD

GitHub Actions CI (`.github/workflows/ci.yml`) runs on every push:
1. Builds the Docker image
2. Starts the container and tests `/health`
3. Validates `/debug/tools` reports ≥ 14 registered tools
4. On `main` branch, runs production smoke tests against Railway

---

## Testing

Run the automated 13-step smoke test suite:

```bash
# Against local server
python tests/cli_tests.py --base-url http://localhost:8000 --api-token $API_TOKEN

# Against Railway production
python tests/cli_tests.py --base-url https://your-app.up.railway.app --api-token $API_TOKEN
```

The suite tests: health check, tool registration, SQL Server connectivity (TCP → ODBC → query), async extraction with job polling, file download with HMAC tokens, SharePoint OAuth, synchronous and async SQL-to-Railway pipelines, and Railway DB connectivity.

See [TEST_PLAN.md](TEST_PLAN.md) for the complete test plan including security testing, expected results by environment, and troubleshooting.

---

## Project Structure

```
SQL-Analysis/
├── src/
│   ├── main.py                    # FastAPI app, MCP setup, lifespan, middleware
│   ├── api/routes.py              # REST endpoints, job creation, background workers
│   ├── config/
│   │   ├── settings.py            # Pydantic Settings (all env vars)
│   │   └── database.py            # Railway PostgreSQL engine factory
│   ├── engine/
│   │   ├── job_manager.py         # PostgreSQL-backed async job tracking
│   │   └── background_jobs.py     # In-memory job manager (reference implementation)
│   ├── services/
│   │   ├── sql_server_client.py   # pyodbc connection pool + query execution
│   │   ├── railway_db_client.py   # SQLAlchemy PostgreSQL client
│   │   ├── sharepoint_client.py   # Microsoft Graph API client
│   │   └── file_manager.py        # CSV generation + file lifecycle management
│   ├── tools/
│   │   ├── database_tools.py      # 6 MCP database tools
│   │   └── sharepoint_tools.py    # 10 MCP SharePoint tools
│   └── utils/
│       ├── security.py            # validate_query(), HMAC token generation/validation
│       ├── logger.py              # Structured logging setup
│       ├── retry.py               # Exponential backoff retry decorator
│       ├── scheduler.py           # APScheduler configuration
│       └── data_validator.py      # DataFrame validation utilities
├── tests/cli_tests.py             # 13-step automated smoke test suite
├── Dockerfile                     # Production Docker image with ODBC Driver 18
├── Procfile                       # Railway process definition
├── railway.toml                   # Railway deployment config
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment variable template
├── .github/workflows/ci.yml       # GitHub Actions CI pipeline
├── REPO_DOCUMENTATION.md          # Deep technical documentation
├── TEST_PLAN.md                   # Complete test plan (4 phases)
└── Project Structure.txt          # Annotated file listing
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [REPO_DOCUMENTATION.md](REPO_DOCUMENTATION.md) | Deep technical documentation — architecture, all classes/functions, data flows, configuration reference, known issues |
| [TEST_PLAN.md](TEST_PLAN.md) | Complete 4-phase test plan — local smoke, security/adversarial, CI, and Railway production testing |
| [Project Structure.txt](Project%20Structure.txt) | Annotated directory listing of all project files |
| [.env.example](.env.example) | Environment variable template with descriptions |

---

## License

This project is proprietary. All rights reserved.
