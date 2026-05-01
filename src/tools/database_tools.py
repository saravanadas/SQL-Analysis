from fastmcp import FastMCP
from src.services.sql_server_client import SQLServerClient
from src.services.railway_db_client import RailwayDBClient
from src.services.file_manager import FileManager
from src.utils.logger import setup_logger
from src.utils.security import validate_query, generate_token
from src.config.settings import settings
import os

logger = setup_logger(__name__)

DATABASE_TOOL_NAMES = [
    "query_sql_server",
    "extract_sql_to_csv",
    "stage_sql_to_railway",
    "query_analytical_db",
]

# =========================
# FIX: Lazy initialization
# =========================

def get_sql_client():
    return SQLServerClient()

def get_railway_client():
    return RailwayDBClient()

def get_file_manager():
    return FileManager()


def load_sql_to_railway(query: str, table_name: str) -> dict:
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
        chunks = sql_client.execute_query_to_dataframe(query)

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

        sql_client = get_sql_client()

        try:
            chunks = sql_client.execute_query_to_dataframe(query, chunksize=1000)
            first_chunk = next(chunks, None)

            if first_chunk is None or first_chunk.empty:
                return "Query returned no results."

            summary = f"Query returned at least {len(first_chunk)} rows in the first chunk.\n\n"
            summary += first_chunk.head(10).to_markdown(index=False)

            if len(first_chunk) > 10:
                summary += f"\n\n... and {len(first_chunk) - 10} more rows in the first chunk."

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

        sql_client = get_sql_client()
        file_manager = get_file_manager()

        # Execute query in streaming mode
        chunks = sql_client.execute_query_to_dataframe(query)

        # Generate file path
        file_id = file_manager.generate_file_id()
        filepath = file_manager.get_file_path(file_id)

        total_rows = 0

        # Write chunks to CSV
        for i, chunk in enumerate(chunks):
            if chunk is None or len(chunk) == 0:
                continue

            mode = 'w' if i == 0 else 'a'
            header = i == 0

            chunk.to_csv(
                filepath,
                mode=mode,
                header=header,
                index=False
            )

            total_rows += len(chunk)

        if total_rows == 0:
            return "No data found for the given query."

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
        result = load_sql_to_railway(query, target_table)
        return result["message"]


    @mcp.tool()
    def query_analytical_db(query: str) -> str:
        """
        Executes a SELECT query on the Railway PostgreSQL analytical database.
        Use this to analyze data that has already been staged.
        """
        # Validate query
        validate_query(query)

        railway_client = get_railway_client()
        
        try:
            df = railway_client.execute_query(query)
            
            if df.empty:
                return "Query returned no results."
            
            # For MCP tools, we return a markdown table or summary
            # Limit results to avoid hitting protocol limits
            summary = f"Query returned {len(df)} rows.\n\n"
            summary += df.head(10).to_markdown(index=False)
            
            if len(df) > 10:
                summary += f"\n\n... and {len(df) - 10} more rows."
                
            return summary
        except Exception as e:
            return f"Error executing analytical query: {str(e)}"
