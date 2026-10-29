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

    async def bootstrap(self) -> None:
        requests = RequestHandler()
        response = await requests.get("/projects")

        items = parse_collection(response)

        self.projects = [
            ProjectItem(
                id=p.get("id"),
                name=p.get("name"),
                description=p.get("description"),
            )
            for p in items
        ]

    def get_id_by_name(self, query: str) -> str:
        query = query.casefold()

        for p in self.projects:
            if query == p.name.casefold():
                return p.id

        names = {p.name.casefold(): p.id for p in self.projects}

        matches = get_close_matches(query, names.keys(), int=1, cutoff=0.6)

        if names and matches:
            return names[matches[0]] if matches else None

        raise ValueError("Project not found.")
