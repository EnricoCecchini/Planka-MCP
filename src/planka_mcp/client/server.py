from mcp.server import MCPServer
from typing import List, Literal
import logging
from contextlib import asynccontextmanager
import sys

from planka_mcp.core import RequestHandler, ProjectIndex
from planka_mcp.utils import parse_collection


logger = logging.getLogger(__name__)

requests = RequestHandler()
projectIndex = ProjectIndex(requests=requests)


@asynccontextmanager
async def lifespan(server: MCPServer):
    await projectIndex.populate()
    print(f"Pre-loaded Project Index with {len(projectIndex.projects)} projects.", file=sys.stderr, flush=True)
    yield {}

mcp = MCPServer("Planka", lifespan=lifespan)


PROJECT_TYPES = Literal["private", "shared"]


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

    # Match project name to ProjectIndex
    project_id = projectIndex.get_id_by_name(query=name)

    if isinstance(project_id, str):
        logger.debug("Project found in registry.")
        result = await requests.get('/projects/' + project_id)
        return result["item"]

    result = await requests.get("/projects")

    projects = parse_collection(result)
    # Use the logger instead of print(): stdout is reserved for the MCP
    # stdio transport, so printing to it can corrupt the protocol stream.
    logger.debug("Searching for project matching %r", name)

    for item in projects:
        if name.lower() in item["name"].lower():
            return item

    return {"message": "Project not found."}


@mcp.tool()
async def project_create(
    name: str, description: str = "", type: PROJECT_TYPES = "private"
) -> dict | None:
    """Create a new project given a name and description."""

    payload = {
        "name": name,
        "description": description,
        "type": type
    }

    resp = await requests.post(endpoint="/projects", payload=payload)
    project = resp.get("item")

    projectIndex.add(
        id=project.get("id"),
        name=project.get("name"),
        description=project.get("description")
    )

    return {"message": f"Project {project.get('name')} created successfully."}


@mcp.resource("projects://Index")
async def project_index() -> None:
    """Print data in the ProjectIndex instance"""

    projectIndex.print()
    return {"data": projectIndex.projects}
