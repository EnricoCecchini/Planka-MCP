from mcp.server import MCPServer
from typing import List, Literal
import logging
from contextlib import asynccontextmanager
import sys

from planka_mcp.core import RequestHandler, ProjectIndex
from planka_mcp.core.ProjectIndex import ProjectItem
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

# Planka spaces sibling positions by this gap (see POSITION_GAP in Planka).
POSITION_GAP = 65536
BOARD_NAME_MAX_LENGTH = 128


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


async def _load_project_boards(project_name: str) -> tuple[ProjectItem, list[dict]]:
    """Resolve a project by name and refresh its boards from Planka.

    Raises:
        ValueError: If the project cannot be found.
    """
    project_id = projectIndex.get_id_by_name(query=project_name)
    project = projectIndex.get_project(project_id) if project_id else None
    if project is None:
        raise ValueError("Project not found.")

    # Planka is the source of truth: boards may have been created or
    # deleted outside this server since the index was populated.
    result = await requests.get(f"/projects/{project.id}")
    included = result.get("included", {}) if isinstance(result, dict) else {}
    boards = included.get("boards", []) or []
    project.set_boards(boards)

    return project, boards


@mcp.tool()
async def project_boards(project_name: str) -> dict:
    """List the existing boards of a project, found by project name."""

    try:
        project, _ = await _load_project_boards(project_name)
    except ValueError as exc:
        return {"message": str(exc)}

    return {
        "project": {"id": project.id, "name": project.name},
        "boards": [b.to_dict() for b in project.boards],
    }


@mcp.tool()
async def board_create(project_name: str, board_name: str) -> dict:
    """Create a new board in a project, found by project name.

    Fails if the project already has a board with the same name
    (case-insensitive).
    """

    board_name = board_name.strip()
    if not board_name:
        return {"message": "Board name must not be empty."}
    if len(board_name) > BOARD_NAME_MAX_LENGTH:
        return {
            "message": f"Board name must be at most {BOARD_NAME_MAX_LENGTH} characters."
        }

    # 1. Identify existing boards for the project.
    try:
        project, boards = await _load_project_boards(project_name)
    except ValueError as exc:
        return {"message": str(exc)}

    # 2. Validate the new board does not already exist.
    existing = project.get_board_by_name(board_name)
    if existing is not None:
        return {
            "message": f"Board '{existing.name}' already exists in project '{project.name}'.",
            "board": existing.to_dict(),
        }

    # 3. Create the board in Planka, appended after the last board.
    last_position = max((b.get("position") or 0 for b in boards), default=0)
    payload = {"name": board_name, "position": last_position + POSITION_GAP}

    resp = await requests.post(endpoint=f"/projects/{project.id}/boards", payload=payload)
    created = resp.get("item") if isinstance(resp, dict) else None
    if not created:
        return {"message": "Planka did not return the created board."}

    # 4. Register the new board in the ProjectIndex (new boards have no tasks).
    board = projectIndex.add_board(
        project_id=project.id,
        id=created.get("id"),
        name=created.get("name"),
        position=created.get("position"),
        tasks=[],
    )

    return {
        "message": f"Board '{board.name}' created successfully in project '{project.name}'.",
        "project": {"id": project.id, "name": project.name},
        "board": board.to_dict(),
    }


@mcp.resource("projects://Index")
async def project_index() -> None:
    """Print data in the ProjectIndex instance"""

    projectIndex.print()
    return {
        "data": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "boards": [b.to_dict() for b in p.boards],
            }
            for p in projectIndex.projects
        ]
    }
