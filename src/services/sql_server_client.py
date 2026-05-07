import queue
import threading
import urllib

import pandas as pd
from sqlalchemy import create_engine

from src.config.settings import settings
from src.utils.logger import setup_logger
from src.utils.retry import retry
from src.utils.security import validate_query

logger = setup_logger(__name__)


class ConnectionPool:
    """Small thread-safe wrapper around SQLAlchemy connections."""

    def __init__(self, engine, maxsize=10, timeout=30):
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
        if getattr(conn, "closed", False):
            self.discard(conn)
            return

        try:
            self._pool.put(conn, block=False)
        except queue.Full:
            self.discard(conn)

    def discard(self, conn):
        try:
            conn.close()
        except Exception:
            pass
        with self._lock:
            self._created = max(0, self._created - 1)

    def close_all(self):
        while not self._pool.empty():
            try:
                conn = self._pool.get(block=False)
                conn.close()
            except Exception:
                pass
        with self._lock:
            self._created = 0


class SQLServerClient:
    """
    Client for interacting with the on-premises Microsoft SQL Server.
    """

    def __init__(self):
        params = urllib.parse.quote_plus(
            f"DRIVER={{{settings.db_driver}}};"
            f"SERVER={settings.sql_server_host},{settings.sql_server_port};"
            f"DATABASE={settings.sql_server_db};"
            f"UID={settings.sql_server_user};"
            f"PWD={settings.sql_server_password};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=yes;"
            f"Connection Timeout={settings.sql_server_connect_timeout_seconds};"
            f"Login Timeout={settings.sql_server_login_timeout_seconds};"
        )
        self.connection_string = f"mssql+pyodbc:///?odbc_connect={params}"

        self.engine = create_engine(
            self.connection_string,
            pool_size=10,
            max_overflow=20,
            pool_timeout=settings.sql_server_pool_timeout_seconds,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"timeout": settings.sql_server_connect_timeout_seconds},
            future=True,
        )
        self._pool = ConnectionPool(
            self.engine,
            maxsize=10,
            timeout=settings.sql_server_pool_timeout_seconds,
        )
        logger.info(f"Initialized SQL Server engine for host: {settings.sql_server_host}")

    @retry(max_attempts=3, delay=3)
    def execute_query_to_dataframe(
        self,
        query: str,
        chunksize: int = 50000,
        query_timeout_seconds: int | None = None,
        force_abort_seconds: int | None = None,
    ):
        """
        Executes a SELECT query in chunks.
        Returns an iterator of DataFrames.
        """
        validate_query(query)

        if query_timeout_seconds is None:
            query_timeout_seconds = settings.sql_server_extract_timeout_seconds
        if force_abort_seconds is None:
            force_abort_seconds = settings.sql_server_force_abort_seconds

        logger.info(
            "Executing SQL Server query "
            f"(first 100 chars): {query[:100]} | chunksize={chunksize} | "
            f"query_timeout_seconds={query_timeout_seconds} | "
            f"force_abort_seconds={force_abort_seconds}"
        )

        conn = None
        abort_timer = None
        aborted = False

        try:
            conn = self._pool.get()

            if force_abort_seconds and force_abort_seconds > 0:
                def _abort():
                    nonlocal aborted
                    aborted = True
                    try:
                        if conn and not conn.closed:
                            conn.close()
                            logger.warning(
                                f"SQL Server query hard-aborted after {force_abort_seconds}s"
                            )
                    except Exception:
                        pass

                abort_timer = threading.Timer(force_abort_seconds, _abort)
                abort_timer.daemon = True
                abort_timer.start()

            with conn.execution_options(timeout=query_timeout_seconds):
                for chunk in pd.read_sql(query, conn, chunksize=chunksize):
                    yield chunk

        except Exception as e:
            logger.error(f"SQL Server query failed: {str(e)}")
            raise
        finally:
            if abort_timer:
                abort_timer.cancel()

            if conn is not None:
                if aborted or getattr(conn, "closed", False):
                    self._pool.discard(conn)
                else:
                    self._pool.put(conn)

    def close(self):
        logger.info("Closing SQL Server connection pool")
        self._pool.close_all()
        self.engine.dispose()
