from mcp.server import MCPServer
from typing import List
import logging

from core import RequestHandler
from utils import parse_collection

logger = logging.getLogger(__name__)

mcp = MCPServer("Planka")

requests = RequestHandler()


@mcp.resource("test://{message}")
def test(message: str) -> str:
    """Test connection by printing a message."""
    return f"Test Message received: {message}"


@mcp.resource("projects://list")
async def projects() -> List[str]:
    """List project titles."""
    result = await requests.get("/projects")

    items = parse_collection(result)
    # Log at DEBUG on stderr: stdout is reserved for the MCP stdio transport.
    logger.debug("Fetched %d projects", len(items))
    return items


@mcp.tool()
async def project_by_name(name: str) -> dict | None:
    """Find a project whose name contains the given text (case-insensitive)."""
    result = await requests.get("/projects")

    projects = parse_collection(result)
    # Use the logger instead of print(): stdout is reserved for the MCP
    # stdio transport, so printing to it can corrupt the protocol stream.
    logger.debug("Searching for project matching %r", name)

    for item in projects:
        if name.lower() in item["name"].lower():
            return item

    raise ValueError("Project name not found.")
