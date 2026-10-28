from planka_mcp.client import mcp

from dotenv import load_dotenv
import logging
import sys


logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

load_dotenv()


if __name__ == "__main__":
    mcp.run()
