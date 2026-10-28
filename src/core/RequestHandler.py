import os
from dotenv import load_dotenv
import httpx
from typing import Any
import logging
import sys


logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

load_dotenv()


class PlankaAPIError(Exception):
    """Raised when HTTP request to Planka's API fails."""


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

    async def _request(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None
    ):
        """
        Method to perform HTTP requests.

        Args:
            - method `str` -> Type of request.
            - url `str` -> Endpoint to request.
            - json `dict[str, Any]` -> JSON payload.
            - params `dict[str, Any]` -> JSON params.
        """
        endpoint = url.lstrip("/")

        try:
            response = await self._client.request(
                method=method,
                url=endpoint,
                params=params,
                json=json
            )

            logger.debug(f"Response: {response}")

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            raise PlankaAPIError(
                f"Planka returned HTTP {exc.response.status_code}"
            ) from exc

        except httpx.RequestError as exc:
            raise PlankaAPIError(
                f"Could not connect to Planka: {exc}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise PlankaAPIError(
                f"Planka returned invalid JSON for "
                f"{method.upper()} {endpoint}"
            ) from exc

    """ Request Methods """
    async def get(
        self, endpoint: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return await self._request(
            method="GET", url=endpoint, json=None, params=params
        )

    async def post(
        self, endpoint: str, *, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._request(
            method="POST", url=endpoint, json=payload
        )

    async def put(
        self, endpoint: str, *, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._request(
            method="PUT", url=endpoint, json=payload
        )

    async def patch(
        self, endpoint: str, *, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._request(
            method="PATCH", url=endpoint, json=payload
        )

    async def delete(self, endpoint: str) -> dict[str, Any] | None:
        return await self._request(method="DELETE", url=endpoint, params=None)

    async def close(self) -> None:
        """Close connection"""

        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
