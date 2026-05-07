import re

import pandas as pd
from sqlalchemy import create_engine, text

from src.config.settings import settings
from src.utils.logger import setup_logger
from src.utils.retry import retry

logger = setup_logger(__name__)


def _validate_table_name(table_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name or ""):
        raise ValueError("Invalid table name")
    return table_name


class RailwayDBClient:
    """
    Client for interacting with the Railway-hosted analytical database.
    """

    def __init__(self):
        self.engine = create_engine(
            settings.railway_db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            pool_timeout=settings.sql_server_pool_timeout_seconds,
            connect_args={"connect_timeout": settings.railway_connect_timeout_seconds},
        )
        logger.info("Initialized Railway DB staging engine.")

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("Railway DB connection verified.")
        except Exception as e:
            logger.error(f"DB connection failed at startup: {str(e)}")

    def _set_statement_timeout(self, conn, statement_timeout_ms: int | None):
        if statement_timeout_ms is None:
            return
        timeout_ms = int(statement_timeout_ms)
        if timeout_ms < 0:
            raise ValueError("statement_timeout cannot be negative")
        conn.execute(text(f"SET statement_timeout = {timeout_ms}"))

    def _get_conn_with_timeout(self, statement_timeout_ms: int | None = None):
        conn = self.engine.connect()
        self._set_statement_timeout(conn, statement_timeout_ms)
        return conn

    @retry(max_attempts=3, delay=2)
    def stage_dataframe(self, df: pd.DataFrame, table_name: str, if_exists: str = "append") -> int:
        """
        Loads a Pandas DataFrame into the Railway database.
        """
        table_name = _validate_table_name(table_name)
        logger.info(f"Staging dataframe of size {len(df)} to table '{table_name}'.")
        try:
            with self.engine.begin() as conn:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists=if_exists,
                    index=False,
                    method="multi",
                    chunksize=settings.railway_insert_chunksize,
                )
            return len(df)
        except Exception as e:
            logger.error(f"Error staging data to Railway DB: {str(e)}")
            raise

    @retry(max_attempts=3, delay=2)
    def insert_dataframe_chunked(self, df: pd.DataFrame, table_name: str, mode: str = "append") -> int:
        """
        Handles chunk-safe insertion.
        """
        table_name = _validate_table_name(table_name)
        logger.info(f"Inserting chunk with {len(df)} rows into '{table_name}' (mode={mode}).")
        try:
            with self.engine.begin() as conn:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists=mode,
                    index=False,
                    method="multi",
                    chunksize=settings.railway_insert_chunksize,
                )
            return len(df)
        except Exception as e:
            logger.error(f"Chunk insert failed: {str(e)}")
            raise

    @retry(max_attempts=3, delay=2)
    def bulk_insert(self, df: pd.DataFrame, table_name: str) -> int:
        """
        Optimized append-mode bulk insert.
        """
        table_name = _validate_table_name(table_name)
        logger.info(f"Bulk inserting {len(df)} records into '{table_name}'.")
        try:
            with self.engine.begin() as conn:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=settings.railway_insert_chunksize,
                )
            return len(df)
        except Exception as e:
            logger.error(f"Bulk insert failed: {str(e)}")
            raise

    def ensure_tracking_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS mcp_file_tracking (
            file_name TEXT PRIMARY KEY,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        with self.engine.begin() as conn:
            conn.execute(text(query))

    def is_file_processed(self, file_name: str) -> bool:
        query = "SELECT 1 FROM mcp_file_tracking WHERE file_name = :file_name"
        with self.engine.begin() as conn:
            result = conn.execute(text(query), {"file_name": file_name}).fetchone()
        return result is not None

    def mark_file_processed(self, file_name: str):
        query = """
        INSERT INTO mcp_file_tracking (file_name)
        VALUES (:file_name)
        ON CONFLICT (file_name) DO NOTHING
        """
        with self.engine.begin() as conn:
            conn.execute(text(query), {"file_name": file_name})

    def ensure_pdf_text_table(self, table_name: str = "sharepoint_pdf_text"):
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
        table_name = _validate_table_name(table_name)
        self.ensure_invoice_file_table(table_name)

        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    f"SELECT file_id, last_modified, file_size, etag, extraction_status "
                    f"FROM {table_name} WHERE file_id = :file_id"
                ),
                {"file_id": file_id},
            ).fetchone()

    def upsert_invoice_file_record(self, record: dict, table_name: str = "sharepoint_invoice_files"):
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
                    {"file_id": file_id},
                )
            df.to_sql(
                name=table_name,
                con=conn,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=settings.railway_insert_chunksize,
            )

        return len(df)

    @retry(max_attempts=3, delay=2)
    def execute_query(self, query: str, statement_timeout_ms: int | None = None) -> pd.DataFrame:
        """
        Executes a bounded analytical SELECT query and returns a DataFrame.
        """
        if statement_timeout_ms is None:
            statement_timeout_ms = settings.railway_query_statement_timeout_ms

        logger.info(f"Executing analytical query: {query[:100]}...")
        try:
            with self.engine.connect() as conn:
                self._set_statement_timeout(conn, statement_timeout_ms)
                try:
                    return pd.read_sql(text(query), conn)
                finally:
                    self._set_statement_timeout(conn, 0)
        except Exception as e:
            logger.error(f"Analytical query failed: {str(e)}")
            raise

    @retry(max_attempts=3, delay=2)
    def execute_query_to_dataframe(
        self,
        query: str,
        chunksize: int = 50000,
        statement_timeout_ms: int | None = None,
    ):
        """
        Executes a SELECT query in chunks for CSV exports.
        """
        if statement_timeout_ms is None:
            statement_timeout_ms = settings.railway_export_statement_timeout_ms

        logger.info(f"Executing analytical query export: {query[:100]}... | chunksize={chunksize}")
        try:
            with self.engine.connect() as conn:
                self._set_statement_timeout(conn, statement_timeout_ms)
                for chunk in pd.read_sql(text(query), conn, chunksize=chunksize):
                    yield chunk
        except Exception as e:
            logger.error(f"Analytical export query failed: {str(e)}")
            raise

    def close(self):
        logger.info("Disposing Railway DB engine and closing all pooled connections")
        self.engine.dispose()
