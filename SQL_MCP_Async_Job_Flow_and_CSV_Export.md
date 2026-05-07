# SQL Analysis MCP — Async Job Flow and CSV Export

*How complex SQL Server extracts are queued, tracked in PostgreSQL, staged, and exported to CSV*

---

## Purpose

This document explains what happens when a user asks the SQL Data Analysis MCP agent to run a complex SQL Server extract and deliver the result as a CSV file. It focuses on the async staging flow, the `public.jobs` table, job status handling, and the final PostgreSQL CSV export path.

---

## Recommended Path for Complex Extracts

- Use **direct SQL Server CSV export** only for simple or medium-sized extracts.
- Use **async SQL Server → PostgreSQL staging** for complex joins, grouped aggregations, balance-forward extracts, reconciliation datasets, and prior timeout cases.
- After async staging completes, **export from PostgreSQL** using the analytical CSV export tool.

```
stage_sql_to_railway_async
  -> /job/{job_id} until completed
  -> extract_analytical_to_csv from staged PostgreSQL table
  -> /download/{file_id}?token=...
```

---

## End-to-End Process Flow

1. The user asks the agent for a complex SQL Server extract and CSV output.
2. The agent chooses `stage_sql_to_railway_async` instead of direct `extract_sql_to_csv`.
3. The MCP service creates a row in `public.jobs` with status `running`.
4. The Railway FastAPI/MCP web container starts a background Python thread.
5. The thread runs the SQL Server `SELECT` query in chunks.
6. Each chunk is inserted into the target PostgreSQL table. The first chunk creates/replaces the table; later chunks append.
7. When staging completes, the `jobs` row is updated to `completed` with `rows_loaded` and target table metadata.
8. If staging fails, the `jobs` row is updated to `failed` with the error message.
9. After completion, the agent exports the staged PostgreSQL table with `extract_analytical_to_csv`.
10. The file download endpoint serves the generated CSV using a signed token.

---

## Where the Jobs Run

The jobs do **not** run inside the SimTheory agent. They run inside the deployed Railway FastAPI/MCP service container. The `jobs` table stores status and metadata, while the actual worker is an in-process Python background thread started by the Railway web service.

| Layer | Role |
|-------|------|
| SimTheory agent | Chooses and calls the MCP tool; reports job IDs, status, and download links. |
| Railway FastAPI/MCP app | Receives MCP/API call, creates job rows, starts worker threads, exposes `/job` and `/download` endpoints. |
| `public.jobs` table | Persists `job_id`, `status`, `result`, `error`, and `created_date`. |
| SQL Server | Source database for the complex extract. |
| Railway PostgreSQL | Landing zone for staged data and source of final PostgreSQL CSV export. |
| Output directory | Temporary storage for generated CSV files before signed download. |

---

## public.jobs Table Behavior

| Column | Purpose |
|--------|---------|
| `job_id` | Unique UUID for the background job. |
| `status` | `running`, `completed`, or `failed`. |
| `result` | JSON result for completed jobs, including `rows_loaded` and target table details. |
| `error` | Failure message for failed jobs. |
| `created_date` | Timestamp when the job row was created. The default should be `NOW()`. |

---

## Status Lifecycle

| Status | Meaning | Next Action |
|--------|---------|-------------|
| `running` | The job row exists and the worker should be processing or waiting on SQL Server/PostgreSQL. | Continue polling `/job/{job_id}` and check target table only as secondary evidence. |
| `completed` | The staging function returned successfully and wrote result metadata. | Export the staged PostgreSQL table using `extract_analytical_to_csv`. |
| `failed` | The worker caught an exception and stored it in `error`. | Read the error to determine whether SQL Server extraction, PostgreSQL insert, or infrastructure failed. |
| `not found` | No job row exists for that `job_id`. | Confirm the correct Railway app/database and `job_id` were used. |

---

## Important Failure Modes

- **Target table is not present yet:** the job may still be running or may have failed before the first SQL Server chunk was inserted.
- **Job remains running for a very long time:** the query may still be running, the SQL Server connection may be blocked, or the Railway container may have restarted.
- **Railway container restart:** the `jobs` row can remain `running`, but the in-process Python worker thread is gone.
- **Wrong `created_date`:** the `jobs.created_date` column may have a fixed timestamp default instead of `NOW()`.
- **Direct SQL Server CSV timeout:** for complex extracts, continue with async staging and PostgreSQL CSV export instead of retrying the same direct export.

---

## Useful Checks

**Check a specific job:**

```sql
SELECT job_id, status, error, created_date, result
FROM public.jobs
WHERE job_id = '<job_id>';
```

**Check the `created_date` default:**

```sql
SELECT column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'jobs'
  AND column_name = 'created_date';
```

**Fix a bad fixed-timestamp default:**

```sql
ALTER TABLE public.jobs
ALTER COLUMN created_date SET DEFAULT NOW();
```

---

## Operational Notes

- The `jobs` table is persistent, but the worker thread is **not**. It only lives inside the current Railway web process.
- The CSV file is **not** created during async staging. It is created later by exporting from the staged PostgreSQL table.
- Old completed/failed jobs should be cleaned up periodically if job volume grows. A safe policy is to delete completed or failed jobs older than 7–14 days.
- Download links expire after approximately 60 minutes because they use signed tokens.

---

## Recommended Agent Instruction

> For complex SQL Server extracts, use `stage_sql_to_railway_async` first.
> Poll `/job/{job_id}` until `completed` or `failed`.
> After completion, export the staged PostgreSQL table with `extract_analytical_to_csv`.
> Do **not** retry direct `extract_sql_to_csv` after it times out for the same complex query.

---

*Converted from `SQL_MCP_Async_Job_Flow_and_CSV_Export.docx` — May 2026*
