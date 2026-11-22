from difflib import get_close_matches

from .RequestHandler import RequestHandler
from planka_mcp.utils import parse_collection, normalize
import logging


logger = logging.getLogger(__name__)


class ProjectBoard:
    def __init__(
        self,
        id: str,
        name: str,
        description: str | None = None,
        position: float | None = None,
        tasks: list[dict] | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.name_normalized = normalize(name)
        self.description = description
        self.position = position
        self.tasks: list[dict] = tasks or []

    def to_dict(self) -> dict:
        """Serialize the board for MCP responses."""
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "tasks": self.tasks,
        }


class ProjectItem:
    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        boards: list[ProjectBoard] | None = None
    ) -> None:
        self.id = id
        self.name = name
        self.name_normalized = normalize(name)
        self.description = description
        self.boards: list[ProjectBoard] = boards or []

    def add_board(
        self,
        id: str,
        name: str,
        position: float | None = None,
        tasks: list[dict] | None = None,
    ) -> ProjectBoard:
        """Add a board to the project, replacing any board with the same ID."""
        board = ProjectBoard(id=id, name=name, position=position, tasks=tasks)
        self.boards = [b for b in self.boards if b.id != id]
        self.boards.append(board)
        return board

    def set_boards(self, boards: list[dict]) -> None:
        """Replace the board list with raw Planka board objects."""
        self.boards = [
            ProjectBoard(
                id=b.get("id"),
                name=b.get("name"),
                position=b.get("position"),
            )
            for b in boards
            if b.get("id") and b.get("name")
        ]

    def get_board_by_name(self, name: str) -> ProjectBoard | None:
        """Return the board whose name matches exactly (case-insensitive)."""
        query = normalize(name)
        for b in self.boards:
            if b.name_normalized == query:
                return b
        return None


class ProjectIndex:
    def __init__(self, requests: RequestHandler):
        self.requests = requests
        self.projects: list[ProjectItem] = []

    async def populate(self) -> None:
        """Populate index registry on startup."""

        response = await self.requests.get("/projects")

        items = parse_collection(response)

        # GET /projects side-loads the accessible boards under
        # ``included.boards``; group them by project to pre-load the index.
        included = response.get("included", {}) if isinstance(response, dict) else {}
        boards_by_project: dict[str, list[dict]] = {}
        for b in included.get("boards", []) or []:
            boards_by_project.setdefault(b.get("projectId"), []).append(b)

        self.projects = []
        for p in items:
            project = ProjectItem(
                id=p.get("id"),
                name=p.get("name"),
                description=p.get("description"),
            )
            project.set_boards(boards_by_project.get(project.id, []))
            self.projects.append(project)

    def print(self) -> None:
        """Print ProjectIndex content."""

        for p in self.projects:
            logger.debug("Project:", p.name)
            logger.debug("Description:", p.description or "No description.")

            print("Boards:")
            for b in p.boards:
                logger.debug("\tBoard:", b.name)
                logger.debug("\tDescription:", b.description)

    def add(
        self, id: str | None, name: str | None, description: str = ""
    ) -> None:
        """
        Add new project to the ProjectIndex

        Args:
            - id `str` -> Project ID.
            - name `str` -> Project name.
            - description `str | None` -> Optional project description.
        """

        if None in (id, name):
            raise ValueError("Projects must have an id and name")

        # Avoid duplicates
        self.projects = [
            p for p in self.projects
            if p.id != id
        ]

        self.projects.append(
            ProjectItem(
                id=id,
                name=name,
                description=description,
            )
        )

    def get_project(self, id: str) -> ProjectItem | None:
        """Return the indexed project with the given ID."""
        for p in self.projects:
            if p.id == id:
                return p
        return None

    def add_board(
        self,
        project_id: str,
        id: str | None,
        name: str | None,
        position: float | None = None,
        tasks: list[dict] | None = None,
    ) -> ProjectBoard:
        """
        Register a board under a project in the ProjectIndex.

        Args:
            - project_id `str` -> ID of the parent project.
            - id `str` -> Board ID.
            - name `str` -> Board name.
            - position `float | None` -> Board position within the project.
            - tasks `list[dict] | None` -> Board tasks (empty for new boards).

        Returns:
            - The registered ProjectBoard.
        """

        if None in (id, name):
            raise ValueError("Boards must have an id and name")

        project = self.get_project(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} is not in the index")

        return project.add_board(id=id, name=name, position=position, tasks=tasks)

    def get_id_by_name(self, query: str) -> str | None:
        """
        Get project ID by fuzzy matching with project title.

        Args:
            - query `str` -> Project name.

        Returns:
            - Project ID
        """

        query = normalize(query=query)

        for p in self.projects:
            if query == p.name_normalized:
                return p.id

        names = {p.name_normalized: p.id for p in self.projects}

        # Use fuzzy matching to get closest match.
        matches = get_close_matches(query, names.keys(), n=1, cutoff=0.6)

        if names and matches:
            return names[matches[0]] if matches else None

        raise ValueError("Project not found.")
