from fastmcp import FastMCP
from src.utils.logger import setup_logger
from src.tools.database_tools import register_database_tools
from src.tools.sharepoint_tools import register_sharepoint_tools
from fastapi import FastAPI
from src.api.routes import router

logger = setup_logger(__name__)

# ✅ FastAPI app (THIS is what Railway uses)
app = FastAPI()
app.include_router(router)

# ✅ MCP setup (DO NOT RUN IT HERE)
def create_mcp() -> FastMCP:
    logger.info("Initializing Unified Data MCP Server...")

    mcp = FastMCP("UnifiedDataMCP")

    register_database_tools(mcp)
    register_sharepoint_tools(mcp)

    logger.info("All tools registered successfully.")
    return mcp
