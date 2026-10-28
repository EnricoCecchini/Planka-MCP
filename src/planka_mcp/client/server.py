from mcp.server import MCPServer

mcp = MCPServer("Planka")


@mcp.resource("test://{message}")
def test(message: str) -> str:
    """Test connection by printing a message."""
    return f"Test Message received: {message}"
