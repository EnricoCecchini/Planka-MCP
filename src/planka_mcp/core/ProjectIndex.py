from difflib import get_close_matches

from .RequestHandler import RequestHandler
from planka_mcp.utils import parse_collection


class ProjectItem:
    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
    ) -> None:
        self.id = id
        self.name = name
        self.description = description


class ProjectIndex:
    def __init__(self):
        self.projects: list[ProjectItem] = []

    @staticmethod
    def _normalize(query: str) -> str:
        """Normalize strings"""
        return query.strip().casefold()

    async def bootstrap(self) -> None:
        """Populate index registry on startup."""

        requests = RequestHandler()
        response = await requests.get("/projects")

        items = parse_collection(response)

        self.projects = [
            ProjectItem(
                id=p.get("id"),
                name=self._normalize(p.get("name")),
                description=p.get("description"),
            )
            for p in items
        ]

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
                name=self._normalize(name),
                description=description,
            )
        )

    def get_id_by_name(self, query: str) -> str | None:
        """
        Get project ID by fuzzy matching with project title.

        Args:
            - query `str` -> Project name.

        Returns:
            - Project ID
        """

        query = self._normalize(query=query)

        for p in self.projects:
            if query == p.name:
                return p.id

        names = {p.name: p.id for p in self.projects}

        # Use fuzzy matching to get closest match.
        matches = get_close_matches(query, names.keys(), n=1, cutoff=0.6)

        if names and matches:
            return names[matches[0]] if matches else None

        raise ValueError("Project not found.")
