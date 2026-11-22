# Planka-MCP

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server for the [Planka](https://planka.app) kanban board.

It lets AI agents (Claude Code, Claude Desktop, or any other MCP client) connect to a Planka instance to read and manage work: load existing projects, boards, lists and tasks (cards), create new projects and tasks, and update task status.

> **Status:** early development. Project lookup and project creation work today. Boards, lists and tasks are on the roadmap below.

## Features

### Available now

| Type     | Name             | Description |
|----------|------------------|-------------|
| Tool     | `project_by_name`| Finds a project by name. It uses exact or fuzzy matching against the in-memory project index and falls back to a substring search over the Planka API. |
| Tool     | `project_create` | Creates a new project with a name, description and type (`private` or `shared`), then adds it to the index. |
| Resource | `projects://list`| Lists all projects visible to the API key. |
| Resource | `projects://Index`| Returns the contents of the in-memory project index. |
| Resource | `test://{message}`| Echoes a message back, for checking the connection. |

### Roadmap

- [ ] Load boards for a project (the `ProjectBoard` model already exists)
- [ ] Load lists and cards (tasks) for a board
- [ ] Create tasks (cards) in a list
- [ ] Update task status by moving cards between lists
- [ ] Create boards and lists

## How it works

```
MCP client (agent)  ──stdio──▶  MCPServer (client/server.py)
                                   │
                                   ├── ProjectIndex  (in-memory cache of projects, fuzzy name lookup)
                                   │
                                   └── RequestHandler (async httpx client, X-Api-Key auth)
                                              │
                                              ▼
                                     Planka REST API
```

- **Startup:** the server's `lifespan` hook fetches all projects once and loads them into a `ProjectIndex`. After that, name lookups resolve to an ID without an extra API call.
- **Transport:** stdio. stdout is reserved for the MCP protocol, so all logging goes to **stderr**.
- **HTTP layer:** `RequestHandler` wraps `httpx.AsyncClient`. It:
  - authenticates with the `X-Api-Key` header,
  - requires `https`, except for localhost and private-network hosts (RFC 1918, link-local, Tailscale `100.64.0.0/10`, IPv6 ULA),
  - accepts only relative endpoints, which blocks absolute-URL and `..` path escapes,
  - caps response size (10 MiB by default),
  - keeps the API key and connection details out of error messages.

## Project structure

```
Planka-MCP/
├── pyproject.toml              # Project metadata and dependencies (uv)
├── uv.lock
├── .python-version             # Python 3.14
├── .env.template               # Template for local configuration
└── src/planka_mcp/
    ├── __init__.py
    ├── main.py                 # Entry point: main() runs the server (`planka-mcp` command)
    ├── client/
    │   └── server.py           # MCPServer instance, lifespan, tools and resources
    ├── core/
    │   ├── RequestHandler.py   # Async Planka REST client (auth, validation, limits)
    │   └── ProjectIndex.py     # ProjectIndex / ProjectItem / ProjectBoard models
    ├── utils/
    │   └── parsing.py          # parse_collection() and normalize() helpers
    └── tests/
        └── test_request_get.py # Manual smoke test: GET /projects
```

## Setup

### Prerequisites

- A running Planka instance and an **API key** for it
- Python **3.14+**
- [uv](https://docs.astral.sh/uv/)

### 1. Install dependencies

```bash
git clone <repo-url> Planka-MCP
cd Planka-MCP
uv sync
```

### 2. Configure the environment

Copy the template and fill in your values:

```bash
cp .env.template .env
```

`.env.template` documents every variable. Only `PLANKA_API_URL` and `PLANKA_API_KEY` are required; the optional ones are already set to their defaults.

| Variable                    | Required | Description |
|-----------------------------|----------|-------------|
| `PLANKA_API_URL`            | yes      | Base URL of your Planka API, e.g. `https://planka.example.com/api`. Must be `https` for public hosts; plain `http` is accepted for `localhost` and private IPs (`10.x`, `172.16–31.x`, `192.168.x`, `169.254.x`, Tailscale `100.64–127.x`, `fc00::`, `fe80::`). |
| `PLANKA_API_KEY`            | yes      | Planka API key, sent as the `X-Api-Key` header. |
| `PLANKA_LOG_LEVEL`          | no       | `DEBUG`, `INFO`, `WARNING`, ... Defaults to `INFO`. |
| `PLANKA_MAX_RESPONSE_BYTES` | no       | Maximum accepted response size in bytes. Defaults to `10485760` (10 MiB). |

Values already exported in your shell take precedence over `.env`. Never commit `.env`.

### 3. Check the connection

```bash
uv run python -m planka_mcp.tests.test_request_get
```

This should print the JSON list of your Planka projects.

### 4. Run the server

```bash
uv run planka-mcp
```

`planka-mcp` is a console script defined in `pyproject.toml` that calls `planka_mcp.main:main`. `uv run python -m planka_mcp.main` does the same thing.

The server talks over stdio, so it is normally launched by an MCP client rather than run by hand.

## Connecting an agent

### Claude Code

```bash
claude mcp add planka -- uv --directory /absolute/path/to/Planka-MCP run planka-mcp
```

### Claude Desktop / other MCP clients

Add an entry to the client's MCP config (for Claude Desktop, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "planka": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/Planka-MCP",
        "run", "planka-mcp"
      ]
    }
  }
}
```

The server reads `.env` from the directory it runs in. You can also pass `PLANKA_API_URL` and `PLANKA_API_KEY` through the client config's `env` block.

## Development notes

- Log with `logging` and never `print()` to stdout, because stdout carries the MCP protocol.
- Planka wraps collections as `{"items": [...], "included": {...}}`. Use `parse_collection()` to unwrap them.
- Project name matching is case-insensitive. `normalize()` handles exact matches, and `difflib.get_close_matches` with a 0.6 cutoff handles fuzzy matches.
