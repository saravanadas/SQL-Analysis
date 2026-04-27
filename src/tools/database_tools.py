from mcp.server.fastmcp import FastMCP
from src.services.sql_server_client import SQLServerClient
from src.services.railway_db_client import RailwayDBClient
from src.services.file_manager import FileManager
from src.utils.logger import setup_logger
from src.utils.security import validate_query

logger = setup_logger(__name__)

# =========================
# FIX: Lazy initialization (VERY IMPORTANT)
# Prevents app crash during startup
# =========================

def get_sql_client():
    return SQLServerClient()

def get_railway_client():
    return RailwayDBClient()

def get_file_manager():
    return FileManager()


def load_sql_to_railway(query: str, table_name: str) -> dict:
    """
    Executes a SQL Server query in chunks and loads the result into Railway DB.

    Flow:
    SQL Server → Chunk → Railway PostgreSQL

    This is optimized for large datasets and prevents memory overload.
    """
    logger.info(f"Starting SQL → Railway pipeline for table '{table_name}'")

    try:
        sql_client = get_sql_client()
        railway_client = get_railway_client()

        # Step 1: Validate query for safety
        validate_query(query)

        # Step 2: Execute query in chunks
        chunks = sql_client.execute_query_to_dataframe(query, chunksize=50000)

        total_rows = 0
        first_chunk = True

        for chunk in chunks:

            if chunk is None or chunk.empty:
                logger.warning("Skipping empty chunk")
                continue

            logger.info(f"Processing chunk with {len(chunk)} rows")

            # Step 3: Insert into Railway
            if first_chunk:
                inserted = railway_client.insert_dataframe_chunked(
                    chunk,
                    table_name,
                    mode="replace"   # first chunk replaces table
                )
                first_chunk = False
            else:
                inserted = railway_client.insert_dataframe_chunked(
                    chunk,
                    table_name,
                    mode="append"
                )

            total_rows += inserted
            logger.info(f"Total rows processed so far: {total_rows}")
            
        logger.info(f"Completed SQL → Railway load. Total rows: {total_rows}")

        return {
            "status": "success",
            "table": table_name,
            "rows_loaded": total_rows
        }

    except Exception as e:
        logger.error(f"SQL → Railway pipeline failed: {str(e)}")
        raise
        

def register_database_tools(mcp: FastMCP):
    """Registers database-related tools to the FastMCP instance."""

    @mcp.tool()
    def extract_sql_to_csv(query: str, output_filename: str) -> str:
        """
        Executes a given SQL query on the on-premises SQL Server and exports the results to a CSV file.
        
        Args:
            query: The T-SQL query string to execute.
            output_filename: The base name for the output CSV file.
            
        Returns:
            A string confirming the path where the CSV was saved.
        """

        sql_client = get_sql_client()
        file_manager = get_file_manager()

        # Execute query in streaming mode (returns chunks instead of full DataFrame)
        chunks = sql_client.execute_query_to_dataframe(query)

        # Generate file path using file manager
        file_id = file_manager.generate_file_id()
        filepath = file_manager.get_file_path(file_id)

        total_rows = 0

        # Write chunks to CSV incrementally (memory efficient)
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

        return f"Successfully extracted {total_rows} rows. File ID: {file_id}"


    @mcp.tool()
    def stage_sql_to_railway(query: str, target_table: str) -> str:
        """
        Extracts data from the on-premises SQL Server and stages it directly 
        into the Railway analytical database. Ideal for ETL operations.
        
        Args:
            query: The T-SQL query string to extract data.
            target_table: The table name in the Railway PostgreSQL database.
            
        Returns:
            A status string detailing the number of rows transferred.
        """

        sql_client = get_sql_client()
        railway_client = get_railway_client()

        # Execute query in streaming mode (chunked extraction)
        chunks = sql_client.execute_query_to_dataframe(query)

        total_rows = 0

        # Stage each chunk into Railway DB (prevents memory overload)
        for chunk in chunks:
            if chunk is None or len(chunk) == 0:
                continue

            if total_rows == 0:
                rows_inserted = railway_client.insert_dataframe_chunked(
                    chunk,
                    target_table,
                    mode="replace"
                )
            else:
                rows_inserted = railway_client.insert_dataframe_chunked(
                    chunk,
                    target_table,
                    mode="append"
                )

            total_rows += rows_inserted

            logger.info(f"Total rows processed so far: {total_rows}")
             
        return f"Successfully transferred {total_rows} rows from On-Prem SQL to Railway table '{target_table}'."
