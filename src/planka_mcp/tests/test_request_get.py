import asyncio

from planka_mcp.core import RequestHandler


async def main():
    async with RequestHandler() as request:
        response = await request.get("/projects")
        print(response)


if __name__ == "__main__":
    asyncio.run(main())
