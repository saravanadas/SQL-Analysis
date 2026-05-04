# STABILIZATION: 2026-05-04 — Added connection pooling + query timeouts
import urllib
import queue
import threading
import time
from sqlalchemy import create_engine, text
import pandas as pd
from src.config.settings import settings
from src.utils.logger import setup_logger
from src.utils.retry import retry
from src.utils.security import validate_query
import logging

logger = setup_logger(__name__)

# Connection pool wrapper with timeout — Added 2026-05-04
class ConnectionPool:
    """Thread-safe SQLAlchemy engine connection pool wrapper."""
    def __init__(self, engine, maxsize=10, timeout=10):
        self.engine = engine
        self.maxsize = maxsize
        self.timeout = timeout
        self._pool = queue.Queue(maxsize)
        self._lock = threading.Lock()
        self._created = 0

    def _create_conn(self):
        return self.engine.connect()

    def get(self):
        try:
            return self._pool.get(block=False)
        except queue.Empty:
            with self._lock:
                if self._created < self.maxsize:
                    self._created += 1
                    return self._create_conn()
            return self._pool.get(block=True, timeout=self.timeout)

    def put(self, conn):
        try:
            self._pool.put(conn, block=False)
        except queue.Full:
            conn.close()

    def close_all(self):
        """Drain and close all pooled connections."""
        while not self._pool.empty():
            try:
                conn = self._pool.get(block=False)
                conn.close()
            except Exception:
                pass


class SQLServerClient:
    """
    Client for interacting with the On-Premises Microsoft SQL Server.
    Utilizes PyODBC and SQLAlchemy with fast_executemany optimization.
    """
    def __init__(self):
        # Format the connection string for PyODBC
        params = urllib.parse.quote_plus(
            f"DRIVER={{{settings.db_driver}}};"
            f"SERVER={settings.sql_server_host},{settings.sql_server_port};"
            f"DATABASE={settings.sql_server_db};"
            f"UID={settings.sql_server_user};"
            f"PWD={settings.sql_server_password};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=yes;"  # Necessary if on-prem lacks proper SSL
            f"Connection Timeout=10;"          # Added 2026-05-04 — hard cap on connect time
            f"Login Timeout=10;"                # Added 2026-05-04 — hard cap on login time
        )
        self.connection_string = f"mssql+pyodbc:///?odbc_connect={params}"
        
        # fast_executemany=True solves the 2100 parameter limit and speeds up inserts drastically
        # Pool initialized 2026-05-04 — tightened all timeout values
        self.engine = create_engine(
            self.connection_string,
            pool_size=10,
            max_overflow=20,
            pool_timeout=10,          # Changed from 30 — 2026-05-04
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"timeout": 10},  # Changed from 30 — 2026-05-04
            future=True
        )
        # Pool wrapper added 2026-05-04
        self._pool = ConnectionPool(self.engine, maxsize=10, timeout=10)
        logger.info(f"Initialized SQL Server engine for host: {settings.sql_server_host}")

    @retry(max_attempts=3, delay=3)
    def execute_query_to_dataframe(self, query: str, chunksize: int = 500, max_execution_time: int = 12):
        """
        Executes query in chunks (streaming).
        Returns iterator of DataFrames.
        
        Args:
            query: SQL query string
            chunksize: Rows per chunk (default 500, reduced from 50000 — 2026-05-04)
            max_execution_time: Seconds to allow query before forcing abort (default 12, added 2026-05-04)
        """
        # Timeout safeguard added 2026-05-04
        validate_query(query)
        
        logger.info(f"Executing query (first 100 chars): {query[:100]} | chunksize={chunksize} | max_execution_time={max_execution_time}")

        conn = None
        try:
            conn = self._pool.get()
            
            # Abort long queries via thread timer — 2026-05-04
            abort_timer = None
            if max_execution_time and max_execution_time > 0:
                def _abort():
                    try:
                        if conn and not conn.closed:
                            conn.close()
                            logger.warning(f"Query aborted after {max_execution_time}s timeout — 2026-05-04")
                    except Exception:
                        pass
                abort_timer = threading.Timer(max_execution_time, _abort)
                abort_timer.daemon = True
                abort_timer.start()

            # Tightened query timeout — 2026-05-04 (was 300s)
            with conn.execution_options(timeout=max_execution_time):
                for chunk in pd.read_sql(query, conn, chunksize=chunksize):
                    yield chunk

            if abort_timer:
                abort_timer.cancel()

        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise
        finally:
            if conn is not None:
                self._pool.put(conn)

    def close(self):
        """Close all pooled connections. Cleanup added 2026-05-04."""
        logger.info("Closing SQL Server connection pool — 2026-05-04")
        self._pool.close_all()
