import os
import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP
from src.utils.logger import setup_logger
from src.tools.database_tools import register_database_tools
from src.tools.sharepoint_tools import register_sharepoint_tools
from src.api.routes import router
from apscheduler.schedulers.background import BackgroundScheduler
from src.services.file_manager import FileManager


import socket
import pyodbc
from fastapi import Header, HTTPException

logger = setup_logger(__name__)

app = FastAPI(title="Unified SQL MCP", version="1.0.0")
app.include_router(router)

def create_mcp() -> FastMCP:
    mcp = FastMCP("UnifiedDataMCP")
    register_database_tools(mcp)
    register_sharepoint_tools(mcp)
    logger.info("All MCP tools registered successfully.")
    return mcp

mcp = create_mcp()

# Mount MCP safely
try:
    app.mount("/mcp", mcp.http_app())
    logger.info("MCP mounted successfully at /mcp")
except Exception as e:
    logger.error(f"MCP mount failed: {str(e)}")

# Health endpoint
@app.get("/health")
def health():
    return {"status": "ok"}
    
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

        return {
            "ok": True,
            "message": "Web can open TCP connection to Railtail",
            "env": env_info,
            "resolved_addresses": addresses,
        }
    except Exception as e:
        return {
            "ok": False,
            "message": "Web could not open TCP connection to Railtail",
            "env": env_info,
            "error_type": e.__class__.__name__,
            "error": str(e),
        }

#Testing
@app.get("/debug/odbc")
def debug_odbc():
    import pyodbc

    try:
        conn = pyodbc.connect(
            "Driver={ODBC Driver 18 for SQL Server};"
            "Server=railtail-production-d464.up.railway.app,1433;"
            "UID=sqlprd_acct_ai;"
            "PWD=Bolthou$#99ai;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=10;"
        )

        cursor = conn.cursor()
        row = cursor.execute("SELECT @@SERVERNAME").fetchone()

        return {
            "ok": True,
            "server": row[0]
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
        
@app.get("/debug/sql")
def debug_sql(authorization: str | None = Header(default=None)):
    _check_debug_auth(authorization)

    host = os.getenv("SQL_SERVER_HOST")
    port = os.getenv("SQL_SERVER_PORT", "1433")
    db = os.getenv("SQL_SERVER_DB")
    user = os.getenv("SQL_SERVER_USER")
    password = os.getenv("SQL_SERVER_PASSWORD")

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
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

        return {
            "ok": True,
            "message": "pyodbc reached SQL Server successfully",
            "value": row[0],
            "server": host,
            "database": db,
        }
    except Exception as e:
        return {
            "ok": False,
            "message": "pyodbc could not reach SQL Server",
            "server": host,
            "database": db,
            "error_type": e.__class__.__name__,
            "error": str(e),
        }

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

@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(cleanup_job, 'interval', hours=1)
    scheduler.start()
    logger.info("Scheduler started")

@app.on_event("shutdown")
def shutdown_scheduler():
    try:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
    except Exception:
        pass

def main():
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
