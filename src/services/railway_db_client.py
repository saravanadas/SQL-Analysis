from sqlalchemy import create_engine
import pandas as pd
import re
from src.config.settings import settings
from src.utils.logger import setup_logger
from src.utils.retry import retry
from sqlalchemy import text

logger = setup_logger(__name__)

def _validate_table_name(table_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name or ""):
        raise ValueError("Invalid table name")
    return table_name

class RailwayDBClient:
    """
    Client for interacting with the Railway-hosted analytical database (PostgreSQL).
    """
    def __init__(self):
        # Railway provides standard database connection URLs via environment variables
        self.engine = create_engine(
            settings.railway_db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            connect_args={"connect_timeout": 100}
        )
        logger.info("Initialized Railway DB staging engine.")
        
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("Railway DB connection verified.")
        except Exception as e:
            logger.error(f"DB connection failed at startup: {str(e)}")

    @retry(max_attempts=3, delay=2)
    def stage_dataframe(self, df: pd.DataFrame, table_name: str, if_exists: str = 'append') -> int:
        """
        Loads a Pandas DataFrame into the Railway Database.
        Uses method='multi' which is highly optimized for PostgreSQL inserts.
        """
        logger.info(f"Staging dataframe of size {len(df)} to table '{table_name}'.")
        try:
            with self.engine.begin() as conn:
                # Write to SQL. method='multi' allows multiple rows per INSERT clause.
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists=if_exists,
                    index=False,
                    method='multi',
                    chunksize=1000 # Prevents memory overload during transaction
                )
                
            return len(df)
        except Exception as e:
            logger.error(f"Error staging data to Railway DB: {str(e)}")
            raise
            
    @retry(max_attempts=3, delay=2)
    def insert_dataframe_chunked(self, df: pd.DataFrame, table_name: str, mode: str = "append") -> int:
        """
        Handles chunk-safe insertion. Automatically switches between replace (first chunk)
        and append (subsequent chunks).
        """
        logger.info(f"Inserting chunk with {len(df)} rows into '{table_name}' (mode={mode}).")
        try:
            with self.engine.begin() as conn:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists=mode,
                    index=False,
                    method='multi',
                    chunksize=1000
                )
            return len(df)
        except Exception as e:
            logger.error(f"Chunk insert failed: {str(e)}")
            raise
    
    @retry(max_attempts=3, delay=2)  # ✅ NEW
    def bulk_insert(self, df: pd.DataFrame, table_name: str) -> int:
        """
        Optimized bulk insert for large datasets (append mode).
        """
        logger.info(f"Bulk inserting {len(df)} records into '{table_name}'.")
        try:
            with self.engine.begin() as conn:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=2000  # Slightly larger for better performance
                )
            return len(df)
        except Exception as e:
            logger.error(f"Bulk insert failed: {str(e)}")
            raise
            
    def ensure_tracking_table(self):
        """
        Creates tracking table if not exists
        """
        query = """
        CREATE TABLE IF NOT EXISTS mcp_file_tracking (
            file_name TEXT PRIMARY KEY,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        with self.engine.begin() as conn:
            conn.execute(text(query))
            
    def is_file_processed(self, file_name: str) -> bool:
        """
        Checks if file already processed
        """
        query = "SELECT 1 FROM mcp_file_tracking WHERE file_name = :file_name"

        with self.engine.begin() as conn:
            result = conn.execute(text(query), {"file_name": file_name}).fetchone()

        return result is not None
        
    def mark_file_processed(self, file_name: str):
        """
        Marks file as processed
        """
        query = """
        INSERT INTO mcp_file_tracking (file_name)
        VALUES (:file_name)
        ON CONFLICT (file_name) DO NOTHING
        """

        with self.engine.begin() as conn:
            conn.execute(text(query), {"file_name": file_name})

    def ensure_pdf_text_table(self, table_name: str = "sharepoint_pdf_text"):
        """
        Creates a table for extracted SharePoint PDF page text.
        """
        table_name = _validate_table_name(table_name)
        query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            sharepoint_path TEXT,
            page_number INTEGER NOT NULL,
            page_text TEXT,
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (file_id, page_number)
        )
        """

        with self.engine.begin() as conn:
            conn.execute(text(query))

    def ensure_invoice_file_table(self, table_name: str = "sharepoint_invoice_files"):
        """
        Creates a table for SharePoint PDF file metadata and extraction status.
        """
        table_name = _validate_table_name(table_name)
        query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            file_id TEXT PRIMARY KEY,
            file_name TEXT NOT NULL,
            sharepoint_path TEXT,
            last_modified TEXT,
            file_size BIGINT,
            etag TEXT,
            page_count INTEGER,
            extraction_status TEXT,
            error_message TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        with self.engine.begin() as conn:
            conn.execute(text(query))

    def get_invoice_file_record(self, file_id: str, table_name: str = "sharepoint_invoice_files"):
        """
        Returns stored SharePoint file metadata for a PDF, if present.
        """
        table_name = _validate_table_name(table_name)
        self.ensure_invoice_file_table(table_name)

        with self.engine.connect() as conn:
            return conn.execute(
                text(f"SELECT file_id, last_modified, file_size, etag, extraction_status FROM {table_name} WHERE file_id = :file_id"),
                {"file_id": file_id}
            ).fetchone()

    def upsert_invoice_file_record(self, record: dict, table_name: str = "sharepoint_invoice_files"):
        """
        Inserts or updates SharePoint PDF file metadata and processing status.
        """
        table_name = _validate_table_name(table_name)
        self.ensure_invoice_file_table(table_name)

        query = f"""
        INSERT INTO {table_name} (
            file_id,
            file_name,
            sharepoint_path,
            last_modified,
            file_size,
            etag,
            page_count,
            extraction_status,
            error_message,
            processed_at
        )
        VALUES (
            :file_id,
            :file_name,
            :sharepoint_path,
            :last_modified,
            :file_size,
            :etag,
            :page_count,
            :extraction_status,
            :error_message,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (file_id) DO UPDATE SET
            file_name = EXCLUDED.file_name,
            sharepoint_path = EXCLUDED.sharepoint_path,
            last_modified = EXCLUDED.last_modified,
            file_size = EXCLUDED.file_size,
            etag = EXCLUDED.etag,
            page_count = EXCLUDED.page_count,
            extraction_status = EXCLUDED.extraction_status,
            error_message = EXCLUDED.error_message,
            processed_at = CURRENT_TIMESTAMP
        """

        with self.engine.begin() as conn:
            conn.execute(text(query), record)

    def store_pdf_text_rows(self, rows, table_name: str = "sharepoint_pdf_text") -> int:
        """
        Stores extracted PDF page text rows in PostgreSQL.
        """
        if not rows:
            return 0

        table_name = _validate_table_name(table_name)
        self.ensure_pdf_text_table(table_name)
        df = pd.DataFrame(rows)
        file_ids = sorted({row["file_id"] for row in rows})

        with self.engine.begin() as conn:
            for file_id in file_ids:
                conn.execute(
                    text(f"DELETE FROM {table_name} WHERE file_id = :file_id"),
                    {"file_id": file_id}
                )
            df.to_sql(
                name=table_name,
                con=conn,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=500
            )

        return len(df)

    @retry(max_attempts=3, delay=2)
    def execute_query(self, query: str) -> pd.DataFrame:
        """
        Executes a SELECT query on the Railway database and returns a DataFrame.
        """
        logger.info(f"Executing analytical query: {query[:100]}...")
        try:
            with self.engine.connect() as conn:
                return pd.read_sql(text(query), conn)
        except Exception as e:
            logger.error(f"Analytical query failed: {str(e)}")
            raise
