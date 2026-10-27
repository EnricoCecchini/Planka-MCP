import os
from dotenv import load_dotenv
import httpx

load_dotenv()


class RequestHandler:
    """
    RequestHandler class to handle async HTTP requests to Planka's REST API.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self.api_token = os.getenv("PLANKA_API_KEY")
        api_url = os.getenv("PLANKA_API_URL")

        if not self.api_token or not api_url:
            raise Exception("Missing env variables")

        self.api_url = api_url.rstrip("/")

        self._client = httpx.AsyncClient(
            base_url=f"{self.api_url}/",
            headers={
                "X-Api-Key": self.api_token,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    async def get(self, endpoint: str):
        endpoint = endpoint.lstrip("/")

        response = await self._client.get(url=endpoint)
        response.raise_for_status()

        print(response)

        return response.json()

    async def close(self) -> None:
        """Close connection"""

        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
