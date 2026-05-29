# Session Handling Changes

## Goal

Improve multi-user and multi-agent safety without breaking existing prompts.
Existing tools still work the same way when no `session_id` is supplied.
When a `session_id` is supplied, write-heavy tools use isolated PostgreSQL
table names so two sessions do not overwrite each other's staged data.

## How The New Session Flow Works

1. The agent calls `create_analysis_session`.
2. The tool returns a UUID session id.
3. The agent passes that `session_id` to staging tools.
4. The code converts the requested logical table into a session-scoped physical
   table name.
5. Example:

   - Requested table: `ap_invoices_vendor_3451899`
   - Session id: `123e4567-e89b-12d3-a456-426614174000`
   - Physical table: `ap_invoices_vendor_3451899_s_123e4567_e89b_12d3_a456_426614174000`

If the agent does not pass `session_id`, the physical table remains the same
as before. That preserves backward compatibility.

## Files Changed

### `src/utils/session.py`

New helper module.

- Creates UUID session ids.
- Sanitizes session ids for PostgreSQL table suffixes.
- Resolves shared table names into session-scoped physical table names.
- Provides an in-process table write lock to prevent overlapping replace/append
  writes to the same physical table.

### `src/tools/database_tools.py`

Changed SQL Server to PostgreSQL staging tools.

- Added MCP tool: `create_analysis_session`.
- Added optional `session_id` to `stage_sql_to_railway`.
- Added optional `session_id` to `stage_sql_to_railway_async`.
- Updated `load_sql_to_railway` so it writes to a session-scoped physical table
  when `session_id` is provided.
- Added table-level locking around the SQL Server to PostgreSQL load sequence.

### `src/tools/sharepoint_tools.py`

Changed SharePoint write tools.

- Added optional `session_id` to `ingest_sharepoint_invoice_pdfs_to_railway`.
- Added optional `session_id` to `ingest_invoice_pdfs`.
- Added optional `session_id` to `stage_sharepoint_pdf_text_to_railway`.
- Added optional `session_id` to `stage_invoice_lines_to_railway`.
- Added optional `session_id` to `sharepoint_to_railway`.
- These tools now write to session-scoped physical tables when `session_id` is
  provided.

### `src/engine/job_manager.py`

Changed background job tracking.

- Added `session_id` column to the `jobs` table.
- Added index on `jobs.session_id`.
- `create_job` now accepts and stores `session_id`.
- `get_job` and `list_jobs` now return `session_id`.

### `src/api/routes.py`

Changed REST staging endpoints.

- `LoadRequest` now accepts optional `session_id`.
- `/load-to-railway` passes `session_id` into the staging pipeline.
- `/load-to-railway/async` passes and records `session_id` for background jobs.

## Why This Helps

Before this change, two users could both stage data into the same PostgreSQL
table and one request could replace or partially overwrite another request's
data.

After this change, the recommended workflow gives each analysis its own
session-scoped physical tables. This allows simultaneous runs to stay separate
while still preserving the old shared-table behavior for existing workflows.

## Recommended Agent Usage

For any multi-step analysis that writes to PostgreSQL:

1. Call `create_analysis_session`.
2. Keep the returned `session_id`.
3. Pass that `session_id` to every staging/write tool.
4. Query the physical table name returned by the staging tool output.

Read-only tools such as `query_sql_server`, `extract_sql_to_csv`, and
`query_analytical_db` do not need session ids unless their SQL points at
session-scoped tables created by earlier staging steps.
