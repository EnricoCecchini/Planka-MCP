from planka_mcp.client import mcp, projectIndex

from dotenv import load_dotenv
import logging
import sys
import asyncio


logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


load_dotenv()


def main() -> None:
    """Run the Planka MCP server over the stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
