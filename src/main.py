import os
import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP
from src.utils.logger import setup_logger
from src.tools.database_tools import register_database_tools
from src.tools.sharepoint_tools import register_sharepoint_tools
from src.api.routes import router

logger = setup_logger(__name__)

# ── FastAPI (HTTP server for Railway) ──
app = FastAPI(title="Unified SQL MCP", version="1.0.0")
app.include_router(router)

# ── FastMCP (MCP protocol tools) ──
def create_mcp() -> FastMCP:
    mcp = FastMCP("UnifiedDataMCP")
    register_database_tools(mcp)
    register_sharepoint_tools(mcp)
    logger.info("All MCP tools registered successfully.")
    return mcp

mcp = create_mcp()

# ── Mount MCP (FIXED for your FastMCP version) ──
try:
    # ✅ Your FastMCP version supports http_app()
    app.mount("/mcp", mcp.http_app())
    logger.info("MCP mounted successfully at /mcp using http_app()")
except Exception as e:
    logger.error(f"Failed to mount MCP: {str(e)}")
    raise

# ── Health Check Endpoint ──
@app.get("/health")
def health():
    return {"status": "ok"}

# ── Background Scheduler ──
from apscheduler.schedulers.background import BackgroundScheduler
from src.services.file_manager import FileManager

# ── Cleanup Job ──
def cleanup_job():
    try:
        fm = FileManager()
        fm.cleanup_old_files(hours=1)
        logger.info("Background cleanup completed successfully.")
    except Exception as e:
        logger.error(f"Background cleanup failed: {str(e)}")

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_job, 'interval', hours=1)
scheduler.start()

# ── Application Entry Point ──
def main():
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
