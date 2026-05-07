# STABILIZATION: 2026-05-04 — Added async staging tool + smaller chunks + time logging
import time

from fastmcp import FastMCP
from src.services.sql_server_client import SQLServerClient
from src.services.railway_db_client import RailwayDBClient
from src.services.file_manager import FileManager
from src.engine.job_manager import JobManager
from src.utils.logger import setup_logger
from src.utils.security import validate_query, generate_token
from src.config.settings import settings

logger = setup_logger(__name__)

DATABASE_TOOL_NAMES = [
    "query_sql_server",
    "extract_sql_to_csv",
    "stage_sql_to_railway",
    "query_analytical_db",
    "extract_analytical_to_csv",
    "stage_sql_to_railway_async",  # Added 2026-05-04
]

# Background job manager for async staging — added 2026-05-04
job_manager = JobManager()

# =========================
# FIX: Lazy initialization
# =========================

def get_sql_client():
    return SQLServerClient()

def get_railway_client():
    return RailwayDBClient()

def get_file_manager():
    return FileManager()


def load_sql_to_railway(
    query: str,
    table_name: str,
    query_timeout_seconds: int | None = None,
    chunksize: int = 50000,
) -> dict:
    """
    Core logic for SQL Server → Railway pipeline.
    Used by both the FastAPI endpoint and the MCP tool.
    """
    logger.info(f"Starting SQL → Railway pipeline for table '{table_name}'")
    
    # Validate query early
    validate_query(query)

    try:
        sql_client = get_sql_client()
        railway_client = get_railway_client()

        # Execute query in streaming mode
        if query_timeout_seconds is None:
            query_timeout_seconds = settings.sql_server_extract_timeout_seconds

        chunks = sql_client.execute_query_to_dataframe(
            query,
            chunksize=chunksize,
            query_timeout_seconds=query_timeout_seconds,
        )

        total_rows = 0

        for chunk in chunks:
            if chunk is None or len(chunk) == 0:
                continue

            mode = "replace" if total_rows == 0 else "append"
            rows_inserted = railway_client.insert_dataframe_chunked(
                chunk,
                table_name,
                mode=mode
            )

            total_rows += rows_inserted
            logger.info(f"Total rows processed so far: {total_rows}")
             
        return {
            "status": "success",
            "table": table_name,
            "rows_loaded": total_rows,
            "query_timeout_seconds": query_timeout_seconds,
            "message": f"Successfully transferred {total_rows} rows to '{table_name}'"
        }
    except Exception as e:
        logger.error(f"SQL → Railway pipeline failed: {str(e)}")
        raise


def register_database_tools(mcp: FastMCP):
    """Registers database-related tools to the FastMCP instance."""

    @mcp.tool()
    def query_sql_server(query: str) -> str:
        """
        Executes a SELECT query on the SQL Server source database and returns
        a small markdown preview of the results.
        """
        validate_query(query)
        start = time.time()  # Timing added 2026-05-04

        sql_client = get_sql_client()

        try:
            # Reduced chunk to stay under Railway timeout — 2026-05-04
            chunks = sql_client.execute_query_to_dataframe(
                query,
                chunksize=500,
                query_timeout_seconds=settings.sql_server_preview_timeout_seconds,
            )
            first_chunk = next(chunks, None)

            if first_chunk is None or first_chunk.empty:
                elapsed = time.time() - start
                logger.info(f"query_sql_server completed in {elapsed:.1f}s — no results — 2026-05-04")
                return "Query returned no results."

            summary = f"Query returned at least {len(first_chunk)} rows in the first chunk.\n\n"
            summary += first_chunk.head(10).to_markdown(index=False)

            if len(first_chunk) > 10:
                summary += f"\n\n... and {len(first_chunk) - 10} more rows in the first chunk."

            elapsed = time.time() - start
            logger.info(f"query_sql_server completed in {elapsed:.1f}s — 2026-05-04")
            return summary
        except Exception as e:
            logger.error(f"SQL Server query tool failed: {str(e)}")
            return f"Error executing SQL Server query: {str(e)}"


    @mcp.tool()
    def extract_sql_to_csv(query: str) -> str:
        """
        Executes a given SQL query on the on-premises SQL Server and exports the results to a CSV file.
        
        Args:
            query: The T-SQL query string to execute.
            
        Returns:
            A message with a secure download URL.
        """
        # Validate query early
        validate_query(query)
        start = time.time()  # Timing added 2026-05-04

        sql_client = get_sql_client()
        file_manager = get_file_manager()

        # Execute query in streaming mode
        chunks = sql_client.execute_query_to_dataframe(
            query,
            query_timeout_seconds=settings.sql_server_extract_timeout_seconds,
        )

        # Generate file path
        file_id = file_manager.generate_file_id()
        filepath = file_manager.get_file_path(file_id)

        total_rows = 0

        # Write chunks to CSV
        for chunk in chunks:
            if chunk is None or len(chunk) == 0:
                continue

            first_write = total_rows == 0

            chunk.to_csv(
                filepath,
                mode="w" if first_write else "a",
                header=first_write,
                index=False,
                encoding="utf-8"
            )

            total_rows += len(chunk)

        if total_rows == 0:
            return "No data found for the given query."

        elapsed = time.time() - start
        logger.info(f"extract_sql_to_csv completed in {elapsed:.1f}s — {total_rows} rows — 2026-05-04")

        # Generate secure download link
        token = generate_token(file_id)
        download_url = f"{settings.app_base_url}/download/{file_id}?token={token}"

        return f"Successfully extracted {total_rows} rows.\n\nDownload Link (expires in 60m):\n{download_url}"


    @mcp.tool()
    def stage_sql_to_railway(query: str, target_table: str) -> str:
        """
        Extracts data from the on-premises SQL Server and stages it directly 
        into the Railway analytical database.
        """
        result = load_sql_to_railway(
            query,
            target_table,
            query_timeout_seconds=settings.sql_server_extract_timeout_seconds,
        )
        return result["message"]

    @mcp.tool()
    def stage_sql_to_railway_async(query: str, target_table: str) -> str:
        """
        Queues a SQL Server -> Railway staging job asynchronously.
        Returns immediately with a job ID. Use /job/{job_id} to check status.
        Added 2026-05-04 to prevent 502 timeouts on large transfers.
        """
        job_id = job_manager.create_job(
            load_sql_to_railway,
            query,
            target_table,
            settings.sql_server_extract_timeout_seconds,
        )
        return (
            "SQL Server to PostgreSQL staging job queued.\n"
            f"Job ID: {job_id}\n"
            f"Status URL: /job/{job_id}\n"
            f"Target table: {target_table}"
        )


    @mcp.tool()
    def query_analytical_db(query: str) -> str:
        """
        Executes a SELECT query on the Railway PostgreSQL analytical database.
        Use this to analyze data that has already been staged.
        """
        # Validate query
        validate_query(query)
        start = time.time()  # Timing added 2026-05-04

        railway_client = get_railway_client()
        
        try:
            df = railway_client.execute_query(
                query,
                statement_timeout_ms=settings.railway_query_statement_timeout_ms,
            )
            
            if df.empty:
                elapsed = time.time() - start
                logger.info(f"query_analytical_db completed in {elapsed:.1f}s — no results — 2026-05-04")
                return "Query returned no results."
            
            # For MCP tools, we return a markdown table or summary
            # Limit results to avoid hitting protocol limits
            summary = f"Query returned {len(df)} rows.\n\n"
            summary += df.head(10).to_markdown(index=False)
            
            if len(df) > 10:
                summary += f"\n\n... and {len(df) - 10} more rows."
                
            elapsed = time.time() - start
            logger.info(f"query_analytical_db completed in {elapsed:.1f}s — 2026-05-04")
            return summary
        except Exception as e:
            return f"Error executing analytical query: {str(e)}"

    @mcp.tool()
    def extract_analytical_to_csv(query: str) -> str:
        """
        Executes a SELECT query on the Railway PostgreSQL analytical database
        and exports the full result set to a CSV file.

        Args:
            query: The PostgreSQL SELECT query string to execute.

        Returns:
            A message with a secure download URL.
        """
        validate_query(query)

        railway_client = get_railway_client()
        file_manager = get_file_manager()

        file_id = file_manager.generate_file_id()
        filepath = file_manager.get_file_path(file_id)
        chunks = railway_client.execute_query_to_dataframe(
            query,
            statement_timeout_ms=settings.railway_export_statement_timeout_ms,
        )

        total_rows = 0

        for i, chunk in enumerate(chunks):
            if chunk is None or len(chunk) == 0:
                continue

            first_write = total_rows == 0
            chunk.to_csv(
                filepath,
                mode="w" if first_write else "a",
                header=first_write,
                index=False,
                encoding="utf-8"
            )

            total_rows += len(chunk)

        if total_rows == 0:
            return "No data found for the given PostgreSQL query."

        token = generate_token(file_id)
        download_url = f"{settings.app_base_url}/download/{file_id}?token={token}"

        return f"Successfully extracted {total_rows} PostgreSQL rows.\n\nDownload Link (expires in 60m):\n{download_url}"
