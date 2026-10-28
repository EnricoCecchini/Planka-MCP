"""Async HTTP request handler for the Planka REST API.

This module exposes :class:`RequestHandler`, a thin wrapper around
``httpx.AsyncClient`` that authenticates against a Planka instance using
the ``X-Api-Key`` header.

Environment variables
---------------------
``PLANKA_API_KEY`` (required)
    The Planka API key, sent as the ``X-Api-Key`` header on every request.
``PLANKA_API_URL`` (required)
    Absolute base URL of the Planka instance, e.g.
    ``https://planka.example.com``. Must use ``https`` for public hosts;
    plain ``http`` is accepted for local or private-network hosts
    (``localhost`` and IP literals on loopback, RFC 1918, link-local,
    100.64.0.0/10 / Tailscale, or IPv6 ULA networks).
``PLANKA_LOG_LEVEL`` (optional)
    Log level for this process (``DEBUG``, ``INFO``, ``WARNING``, ...).
    Defaults to ``INFO``.
``PLANKA_MAX_RESPONSE_BYTES`` (optional)
    Maximum size, in bytes, of a response body accepted from Planka.
    Defaults to 10 MiB (10485760).
"""

import ipaddress
import json
import logging
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

__all__ = ["PlankaAPIError", "PlankaConfigError", "RequestHandler"]

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

# ``load_dotenv`` runs at import time so configuration can be provided via a
# local ``.env`` file. It does **not** override variables that are already
# present in the environment, so explicitly exported values always win.
load_dotenv()

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure process-wide logging once, writing to stderr.

    The MCP *stdio* transport reserves **stdout** for the protocol, so all
    log output must go to **stderr**. The root logger is only configured
    when it has no handlers yet, so an existing logging setup (for example
    one installed by an embedding application) is left untouched.

    The level is read from ``PLANKA_LOG_LEVEL`` and defaults to ``INFO`` so
    production processes are not flooded with DEBUG output. An unknown level
    name falls back to ``INFO`` as well.
    """
    level_name = os.getenv("PLANKA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(level)


_configure_logging()


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

# Endpoints must be simple relative paths such as ``projects`` or
# ``projects/123/issues``. The character class deliberately excludes ``:``
# (which would let an absolute URL such as ``http://evil.example`` bypass
# the configured base URL) and ``.`` (which would allow ``..`` path
# traversal segments).
_ENDPOINT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_/-]*$")

# HTTP methods accepted by the Planka API.
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

# Primitive types ``httpx`` accepts as individual query parameter values.
_PARAM_VALUE_TYPES = (str, int, float, bool)

# Hosts/networks for which a plain ``http`` base URL is acceptable, because
# the traffic stays on the local or private network: loopback, RFC 1918
# private ranges, link-local, the shared address space 100.64.0.0/10 (used
# by Tailscale), and IPv6 unique-local / link-local ranges. Public DNS
# hosts still require ``https``.
_LOCAL_HOSTNAMES = frozenset({"localhost"})
_LOCAL_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _is_local_host(hostname: str) -> bool:
    """Return True if ``hostname`` is a local or private-network host.

    ``localhost`` and IP literals on the local/private networks listed in
    ``_LOCAL_NETWORKS`` qualify. Plain DNS names are treated as remote
    (https required) because their address is unknown without a lookup.
    """
    if hostname in _LOCAL_HOSTNAMES:
        return True
    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return any(host_ip in network for network in _LOCAL_NETWORKS)

# Default response size cap: 10 MiB.
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class PlankaConfigError(Exception):
    """Raised when the environment configuration is missing or invalid."""


class PlankaAPIError(Exception):
    """Raised when an HTTP request to the Planka API fails."""


class RequestHandler:
    """Async HTTP client for the Planka REST API.

    The handler reads ``PLANKA_API_KEY`` and ``PLANKA_API_URL`` from the
    environment and sends the key as the ``X-Api-Key`` header on every
    request. Use it as an async context manager (or call :meth:`close`) so
    the underlying connection pool is released:

    .. code-block:: python

        async with RequestHandler() as api:
            projects = await api.get("/projects")
    """

    def __init__(self, timeout: float = 30.0) -> None:
        """Create the handler from the environment configuration.

        Args:
            timeout: Timeout in seconds, applied to every phase of a
                request (connect, read, write and pool).

        Raises:
            PlankaConfigError: If ``PLANKA_API_KEY`` or ``PLANKA_API_URL``
                is missing, or if the URL is not a valid ``https`` URL
                (``http`` is only accepted for local or private-network
                hosts).
        """
        api_token = os.getenv("PLANKA_API_KEY")
        api_url = os.getenv("PLANKA_API_URL")

        if not api_token or not api_url:
            # Keep the public message generic so it does not reveal *which*
            # variable is missing; the detail is logged for local debugging.
            logger.debug(
                "Missing configuration: api_key set=%s, api_url set=%s",
                bool(api_token),
                bool(api_url),
            )
            raise PlankaConfigError(
                "Missing environment variables: PLANKA_API_KEY and "
                "PLANKA_API_URL are required"
            )

        self.api_url = self._resolve_api_url(api_url)

        # Keep the raw key private so that logging or serialising the
        # handler instance does not expose the secret.
        self._api_token = api_token

        # Cap response bodies so a misbehaving server cannot exhaust memory.
        self._max_response_bytes = self._resolve_max_response_bytes(
            os.getenv("PLANKA_MAX_RESPONSE_BYTES")
        )

        self._client = httpx.AsyncClient(
            base_url=f"{self.api_url}/",
            headers={
                "X-Api-Key": self._api_token,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    @staticmethod
    def _resolve_api_url(api_url: str) -> str:
        """Validate and normalise the configured base URL.

        The URL must be absolute and must use ``https``, because the API
        key is transmitted on every request. Plain ``http`` is only
        accepted for local or private-network hosts (see
        :func:`_is_local_host`).

        Args:
            api_url: Value of ``PLANKA_API_URL``.

        Returns:
            The URL with any trailing slash removed.

        Raises:
            PlankaConfigError: If the URL is not an absolute ``http(s)``
                URL, has no host, or uses ``http`` for a public host.
        """
        parsed = urlparse(api_url)
        if parsed.scheme not in ("http", "https"):
            raise PlankaConfigError(
                "PLANKA_API_URL must be an absolute http(s) URL, "
                f"got: {api_url!r}"
            )
        if not parsed.hostname:
            raise PlankaConfigError(
                f"PLANKA_API_URL must include a host, got: {api_url!r}"
            )
        if parsed.scheme == "http" and not _is_local_host(parsed.hostname or ""):
            raise PlankaConfigError(
                "PLANKA_API_URL must use https (http is only allowed for "
                f"local/private-network hosts), got: {api_url!r}"
            )
        return api_url.rstrip("/")

    @staticmethod
    def _resolve_max_response_bytes(raw: str | None) -> int:
        """Parse the optional response size cap in bytes.

        Args:
            raw: Value of ``PLANKA_MAX_RESPONSE_BYTES``, or ``None`` when
                the variable is not set.

        Returns:
            The configured cap, or 10 MiB when unset.

        Raises:
            PlankaConfigError: If the value is not a positive integer.
        """
        if raw is None:
            return _DEFAULT_MAX_RESPONSE_BYTES
        try:
            value = int(raw)
        except ValueError:
            raise PlankaConfigError(
                "PLANKA_MAX_RESPONSE_BYTES must be an integer, "
                f"got: {raw!r}"
            ) from None
        if value <= 0:
            raise PlankaConfigError(
                f"PLANKA_MAX_RESPONSE_BYTES must be positive, got: {value}"
            )
        return value

    @staticmethod
    def _validate_params(params: dict[str, Any]) -> None:
        """Ensure query parameters are types ``httpx`` can serialise.

        ``httpx`` percent-encodes parameter values, which prevents them
        from leaking into other parts of the request, but invalid types
        would raise deep inside the library. Checking up front gives a
        clear, actionable error.

        Args:
            params: Query parameters to send.

        Raises:
            ValueError: If a key is not a non-empty string, or a value is
                not a string, number, boolean, or list of those.
        """
        for key, value in params.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"Invalid query parameter key: {key!r}")
            if isinstance(value, (list, tuple)):
                if not all(isinstance(item, _PARAM_VALUE_TYPES) for item in value):
                    raise ValueError(
                        f"Invalid values for query parameter {key!r}"
                    )
            elif not isinstance(value, _PARAM_VALUE_TYPES):
                raise ValueError(
                    f"Invalid value for query parameter {key!r}: {value!r}"
                )

    async def _request(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        """Perform an HTTP request against the Planka API.

        Args:
            method: HTTP method (``GET``, ``POST``, ``PUT``, ``PATCH`` or
                ``DELETE``). Case-insensitive.
            url: Relative endpoint, e.g. ``"/projects"``. Leading slashes
                are stripped; the remainder must match a simple path
                pattern (letters, digits, ``_``, ``-``, ``/``). This
                rejects absolute URLs and ``..`` segments that would
                escape the configured base URL.
            json_body: Optional JSON request body. Named ``json_body``
                (rather than ``json``) so it does not shadow the stdlib
                ``json`` module used to decode the response.
            params: Optional query parameters. Keys must be non-empty
                strings; values must be strings, numbers, booleans, or
                lists of those.

        Returns:
            The decoded JSON body: an object (``dict``), an array
            (``list``), or ``None`` for an empty response.

        Raises:
            ValueError: If ``method``, ``url`` or ``params`` is malformed.
            PlankaAPIError: If the request fails, the HTTP status is an
                error, the body is not valid JSON, or the body exceeds the
                configured size limit.
        """
        method = method.upper()
        if method not in _ALLOWED_METHODS:
            raise ValueError(f"Unsupported HTTP method: {method!r}")

        endpoint = url.lstrip("/")
        if not _ENDPOINT_PATTERN.fullmatch(endpoint):
            raise ValueError(
                "Endpoint must be a relative path of letters, digits, '_', "
                f"'-' and '/', got: {url!r}"
            )

        if params is not None:
            self._validate_params(params)

        try:
            # Stream the response so the size cap can be enforced while
            # reading, instead of buffering an unbounded body first.
            async with self._client.stream(
                method=method,
                url=endpoint,
                params=params,
                json=json_body,
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > self._max_response_bytes:
                        raise PlankaAPIError(
                            f"Planka response exceeds "
                            f"{self._max_response_bytes} bytes"
                        )

                logger.debug("Response: %s", response)

                response.raise_for_status()

                # Parse from the buffered body: a streaming response does
                # not expose ``.json()``/``.content`` once the stream has
                # been consumed by ``aiter_bytes()``.
                try:
                    payload = json.loads(bytes(body))
                except ValueError as exc:
                    raise PlankaAPIError(
                        f"Planka returned invalid JSON for "
                        f"{method} {endpoint}"
                    ) from exc

        except httpx.HTTPStatusError as exc:
            raise PlankaAPIError(
                f"Planka returned HTTP {exc.response.status_code}"
            ) from exc

        except httpx.RequestError as exc:
            # Keep the exception text out of the public message: it can
            # embed the full URL and OS/SSL details. The detail is logged
            # for server-side debugging and preserved via `from exc`.
            logger.debug("Could not connect to Planka: %s", exc)
            raise PlankaAPIError("Could not connect to Planka") from exc

        # The endpoints used by this client return JSON objects or arrays.
        # Anything else (a bare string, number, ...) is a contract
        # violation, surfaced explicitly instead of breaking callers.
        if payload is None or isinstance(payload, (dict, list)):
            return payload
        raise PlankaAPIError(
            f"Planka returned an unexpected JSON payload of type "
            f"{type(payload).__name__} for {method} {endpoint}"
        )

    """ Request Methods """

    async def get(
        self, endpoint: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[Any] | None:
        """Perform a ``GET`` request.

        Args:
            endpoint: Relative endpoint, e.g. ``"/projects"``.
            params: Optional query parameters.
        """
        return await self._request(
            method="GET", url=endpoint, json_body=None, params=params
        )

    async def post(
        self, endpoint: str, *, payload: dict[str, Any]
    ) -> dict[str, Any] | list[Any] | None:
        """Perform a ``POST`` request with a JSON body.

        Args:
            endpoint: Relative endpoint, e.g. ``"/projects"``.
            payload: JSON request body.
        """
        return await self._request(
            method="POST", url=endpoint, json_body=payload
        )

    async def put(
        self, endpoint: str, *, payload: dict[str, Any]
    ) -> dict[str, Any] | list[Any] | None:
        """Perform a ``PUT`` request with a JSON body.

        Args:
            endpoint: Relative endpoint, e.g. ``"/projects/1"``.
            payload: JSON request body.
        """
        return await self._request(
            method="PUT", url=endpoint, json_body=payload
        )

    async def patch(
        self, endpoint: str, *, payload: dict[str, Any]
    ) -> dict[str, Any] | list[Any] | None:
        """Perform a ``PATCH`` request with a JSON body.

        Args:
            endpoint: Relative endpoint, e.g. ``"/projects/1"``.
            payload: JSON request body.
        """
        return await self._request(
            method="PATCH", url=endpoint, json_body=payload
        )

    async def delete(self, endpoint: str) -> dict[str, Any] | list[Any] | None:
        """Perform a ``DELETE`` request.

        Args:
            endpoint: Relative endpoint, e.g. ``"/projects/1"``.
        """
        return await self._request(method="DELETE", url=endpoint, params=None)

    async def close(self) -> None:
        """Close the underlying client and release its connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> "RequestHandler":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
