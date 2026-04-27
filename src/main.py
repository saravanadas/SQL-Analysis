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
    mcp = FastMCP("UnifiedDataMCP", dependencies=["pandas", "sqlalchemy"])
    register_database_tools(mcp)
    register_sharepoint_tools(mcp)
    logger.info("All MCP tools registered successfully.")
    return mcp

# Mount MCP as a sub-application on /mcp
mcp = create_mcp()
app.mount("/mcp", mcp.streamable_http_app())

@app.get("/health")
def health():
    return {"status": "ok"}

def main():
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
