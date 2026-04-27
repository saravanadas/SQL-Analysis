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

# Mount MCP — try methods in order of newest → oldest fastmcp API
mcp_app = None

# List of known methods to get the ASGI/HTTP app from FastMCP
methods = ["streamable_http_app", "sse_app", "create_asgi_app", "get_asgi_app", "asgi_app"]

for method_name in methods:
    if hasattr(mcp, method_name):
        try:
            mcp_app = getattr(mcp, method_name)()
            logger.info(f"Mounted MCP via {method_name}")
            break
        except Exception as e:
            logger.warning(f"Found {method_name} but failed to call it: {str(e)}")

if not mcp_app:
    # Final fallback: check if the object itself is an ASGI app
    logger.error("Failed to mount MCP: No compatible app method found on FastMCP instance")
    raise RuntimeError("FastMCP instance lacks a valid ASGI app method (tried streamable_http_app, sse_app, create_asgi_app, etc.)")

app.mount("/mcp", mcp_app)

@app.get("/health")
def health():
    return {"status": "ok"}

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

def main():
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
