import urllib
from sqlalchemy import create_engine, text
import pandas as pd
from src.config.settings import settings
from src.utils.logger import setup_logger
from src.utils.retry import retry
from src.utils.security import validate_query
import logging

logger = setup_logger(__name__)

class SQLServerClient:
    """
    Client for interacting with the On-Premises Microsoft SQL Server.
    Utilizes PyODBC and SQLAlchemy with fast_executemany optimization.
    """
    def __init__(self):
        # Format the connection string for PyODBC
        params = urllib.parse.quote_plus(
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={settings.sql_server_host},{settings.sql_server_port};"
            f"DATABASE={settings.sql_server_db};"
            f"UID={settings.sql_server_user};"
            f"PWD={settings.sql_server_password};"
            f"TrustServerCertificate=yes;" # Necessary if on-prem lacks proper SSL
        )
        self.connection_string = f"mssql+pyodbc:///?odbc_connect={params}"
        
        # fast_executemany=True solves the 2100 parameter limit and speeds up inserts drastically
        self.engine = create_engine(
            self.connection_string,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"timeout": 30},
            future=True
        )
        logger.info(f"Initialized SQL Server engine for host: {settings.sql_server_host}")

    @retry(max_attempts=3, delay=3)
    def execute_query_to_dataframe(self, query: str, chunksize: int = 50000):
        """
        Executes query in chunks (streaming).
        Returns iterator of DataFrames.
        """
        validate_query(query)
        
        logger.info(f"Executing query (first 100 chars): {query[:100]} | chunksize={chunksize}")

        try:
            with self.engine.connect().execution_options(timeout=300) as conn:
                return pd.read_sql(query, conn, chunksize=chunksize)

        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise
