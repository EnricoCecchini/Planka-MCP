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


async def run_main():
    await projectIndex.bootstrap()


if __name__ == "__main__":
    asyncio.run(run_main())
    mcp.run()
