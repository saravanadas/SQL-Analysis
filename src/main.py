# STABILIZATION: 2026-05-04 — Added ASGI timeout middleware + graceful pool cleanup
import asyncio
import os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP
from src.utils.logger import setup_logger
from src.tools.database_tools import register_database_tools
from src.tools.sharepoint_tools import register_sharepoint_tools
from src.tools.database_tools import DATABASE_TOOL_NAMES
from src.tools.sharepoint_tools import SHAREPOINT_TOOL_NAMES
from src.api.routes import router
from apscheduler.schedulers.background import BackgroundScheduler
from src.services.file_manager import FileManager

import socket
import pyodbc
from fastapi import Header, HTTPException
from src.config.settings import settings
from sqlalchemy import create_engine, text

logger = setup_logger(__name__)

def create_mcp() -> FastMCP:
    mcp = FastMCP("UnifiedDataMCP")
    register_database_tools(mcp)
    register_sharepoint_tools(mcp)
    logger.info("All MCP tools registered successfully.")
    return mcp

mcp = create_mcp()
mcp_app = mcp.http_app(path="/mcp")

# Cleanup job
def cleanup_job():
    try:
        fm = FileManager()
        fm.cleanup_old_files(hours=1)
        logger.info("Background cleanup completed successfully.")
    except Exception as e:
        logger.error(f"Background cleanup failed: {str(e)}")

# Scheduler lifecycle
scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(cleanup_job, 'interval', hours=1, id="cleanup_job", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        async with mcp_app.lifespan(app):
            yield
    finally:
        # Graceful pool cleanup added 2026-05-04
        try:
            from src.services.sql_server_client import SQLServerClient
            client = SQLServerClient()
            if hasattr(client, '_pool') and client._pool:
                client.close()
        except Exception:
            pass
        try:
            from src.services.railway_db_client import RailwayDBClient
            client = RailwayDBClient()
            if hasattr(client, 'engine') and client.engine:
                client.close()
        except Exception:
            pass
        try:
            scheduler.shutdown()
            logger.info("Scheduler stopped")
        except Exception:
            pass

app = FastAPI(title="Unified SQL MCP", version="1.0.0", lifespan=lifespan)
app.include_router(router)

# Timeout middleware added 2026-05-04 — prevents Railway 502 by returning 504 early
class TimeoutMiddleware:
    def __init__(self, app, timeout_seconds=12):
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await asyncio.wait_for(
                self.app(scope, receive, send),
                timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            # 504 instead of letting Railway 502 — 2026-05-04
            await send({
                "type": "http.response.start",
                "status": 504,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"detail":"Request timed out. Try a smaller query or use the async staging endpoint."}',
            })

app.add_middleware(TimeoutMiddleware, timeout_seconds=12)

# Mount MCP safely
try:
    app.mount("/mcp", mcp_app)
    logger.info("MCP mounted successfully at /mcp")
except Exception as e:
    logger.error(f"MCP mount failed: {str(e)}")

# Health endpoint
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/tools")
def debug_tools(authorization: str | None = Header(default=None)):
    _check_debug_auth(authorization)
    tools = DATABASE_TOOL_NAMES + SHAREPOINT_TOOL_NAMES
    return {
        "tool_count": len(tools),
        "tools": tools,
    }

#For Testing
def _check_debug_auth(authorization: str | None):
    expected = os.getenv("API_TOKEN")
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/debug/tcp")
def debug_tcp(authorization: str | None = Header(default=None)):
    _check_debug_auth(authorization)
    host = os.getenv("SQL_SERVER_HOST")
    port_raw = os.getenv("SQL_SERVER_PORT", "1433")
    port = int(port_raw)
    env_info = {
        "SQL_SERVER_HOST": repr(host),
        "SQL_SERVER_PORT": repr(port_raw),
        "SQL_SERVER_DB": repr(os.getenv("SQL_SERVER_DB")),
        "SQL_SERVER_USER": repr(os.getenv("SQL_SERVER_USER")),
    }
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = sorted({item[4][0] for item in resolved})
        sock = socket.create_connection((host, port), 5)
        sock.close()
        return {"ok": True, "message": "Web can open TCP connection to Railtail", "env": env_info, "resolved_addresses": addresses}
    except Exception as e:
        return {"ok": False, "message": "Web could not open TCP connection to Railtail", "env": env_info, "error_type": e.__class__.__name__, "error": str(e)}

#Testing
@app.get("/debug/odbc")
def debug_odbc(authorization: str | None = Header(default=None)):
    _check_debug_auth(authorization)
    import pyodbc
    host = os.getenv("SQL_SERVER_HOST")
    port = os.getenv("SQL_SERVER_PORT", "1433")
    db = os.getenv("SQL_SERVER_DB")
    user = os.getenv("SQL_SERVER_USER")
    password = os.getenv("SQL_SERVER_PASSWORD")
    driver = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    conn_str = (
        f"Driver={{{driver}}};"
        f"Server={host},{port};"
        f"Database={db};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=10;"
    )
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        row = cursor.execute("SELECT @@SERVERNAME").fetchone()
        cursor.close()
        conn.close()
        return {"ok": True, "server": row[0], "host": host, "port": port, "database": db}
    except Exception as e:
        return {"ok": False, "host": host, "port": port, "database": db, "error_type": e.__class__.__name__, "error": str(e)}

@app.get("/debug/sql")
def debug_sql(authorization: str | None = Header(default=None)):
    _check_debug_auth(authorization)
    host = os.getenv("SQL_SERVER_HOST")
    port = os.getenv("SQL_SERVER_PORT", "1433")
    db = os.getenv("SQL_SERVER_DB")
    user = os.getenv("SQL_SERVER_USER")
    password = os.getenv("SQL_SERVER_PASSWORD")
    conn_str = (
        f"DRIVER={{{os.getenv('DB_DRIVER', 'ODBC Driver 18 for SQL Server')}}};"
        f"SERVER={host},{port};"
        f"DATABASE={db};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    try:
        conn = pyodbc.connect(conn_str, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return {"ok": True, "message": "pyodbc reached SQL Server successfully", "value": row[0], "server": host, "database": db}
    except Exception as e:
        return {"ok": False, "message": "pyodbc could not reach SQL Server", "server": host, "database": db, "error_type": e.__class__.__name__, "error": str(e)}

@app.get("/debug/railway")
def debug_railway(authorization: str | None = Header(default=None)):
    """Test Railway PostgreSQL analytical DB connectivity via SELECT 1."""
    _check_debug_auth(authorization)
    db_url = settings.railway_db_url if hasattr(settings, "railway_db_url") else os.getenv("RAILWAY_DB_URL", "")
    try:
        engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 AS railway_ok"))
            row = result.fetchone()
        return {"ok": True, "message": "Railway PostgreSQL connection working", "value": row[0] if row else None, "url_prefix": db_url[:40] + "..." if db_url else ""}
    except Exception as e:
        return {"ok": False, "message": "Railway PostgreSQL connection failed", "error_type": e.__class__.__name__, "error": str(e), "url_prefix": db_url[:40] + "..." if db_url else ""}

def main():
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_keep_alive=5)  # timeout_keep_alive added 2026-05-04

if __name__ == "__main__":
    main()
