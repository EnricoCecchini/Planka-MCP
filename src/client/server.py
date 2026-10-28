from mcp.server import MCPServer
from typing import List
import logging

from core import RequestHandler


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
    projects = await requests.get("/projects")
    logger.info(projects)
    return projects.get("items")


@mcp.tool()
async def project_by_name(name: str) -> dict | None:
    """List project titles."""
    resp = await requests.get("/projects")
    projects = resp.get("items", [])

    print(projects)

    for item in projects:
        if name.lower() in item["name"].lower():
            return item

    raise ValueError("Project name not found.")
