from fastmcp import FastMCP
from src.utils.logger import setup_logger
from src.tools.database_tools import register_database_tools
from src.tools.sharepoint_tools import register_sharepoint_tools
from fastapi import FastAPI
from src.api.routes import router

app = FastAPI()
app.include_router(router)

logger = setup_logger(__name__)

def create_app() -> FastMCP:
    """
    Factory function to instantiate and configure the FastMCP server.
    """
    logger.info("Initializing Unified Data MCP Server...")
    
    # Initialize the server instance
    # Depending on the version, fastmcp or mcp.server.fastmcp is used.
    # We use "fastmcp" from PrefectHQ for enhanced capabilities.
    mcp = FastMCP("UnifiedDataMCP", dependencies=["pandas", "sqlalchemy"])
    
    # Register all tool modules
    register_database_tools(mcp)
    register_sharepoint_tools(mcp)
    
    logger.info("All tools registered successfully.")
    return mcp

def main():
    """Main execution function."""
    app = create_app()
    # run() starts the JSON-RPC event loop. 
    # By default, it communicates via Stdio, making it fully compatible with Claude Desktop and other LLM clients.
    logger.info("Starting MCP protocol listener...")
    app.run()

if __name__ == "__main__":
    main()
