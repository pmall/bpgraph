"""The MCP server, `bpgraph-mcp`: the only thing consumers see.

Each endpoint of the query API is a tool of the same name, signature and
description, which forwards its arguments to the API at `BPGRAPH_API` and
hands back its answer. The server reaches neither the graph nor the vaults
itself. It serves streamable HTTP at `/mcp`, on `MCP_HOST` and `MCP_PORT`.
"""

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from bpgraph.api.endpoints import ENDPOINTS, Endpoint

INSTRUCTIONS = (Path(__file__).parent / "guide" / "server.md").read_text().strip()
"""Every agent receives these, subagents included, and Claude Code keeps the
first 2,048 characters only: what every query needs, first."""

API = os.environ.get("BPGRAPH_API", "http://127.0.0.1:8000")

server = MCPServer(name="bpgraph", instructions=INSTRUCTIONS)
client = httpx2.AsyncClient(base_url=API, timeout=300)


def _lean(schema: Any) -> Any:
    """A parameter schema without what costs tokens and tells an agent
    nothing: the titles, and the null branch of an optional parameter."""
    if isinstance(schema, list):
        return [_lean(item) for item in cast(list[Any], schema)]
    if not isinstance(schema, dict):
        return schema
    lean = {
        key: _lean(value)
        for key, value in cast(dict[str, Any], schema).items()
        if not (key == "title" and isinstance(value, str))
    }
    branches = lean.get("anyOf")
    if isinstance(branches, list):
        kept = [b for b in cast(list[Any], branches) if b != {"type": "null"}]
        if len(kept) == 1:
            del lean["anyOf"]
            lean = {**kept[0], **lean}
            if lean.get("default", ...) is None:
                del lean["default"]
    return lean


def _tool(endpoint: Endpoint) -> Callable[..., Awaitable[str]]:
    """A function with the endpoint's signature, calling it over HTTP and
    handing back the API's text, the size `max_tokens` was checked against."""

    async def call(**arguments: Any) -> str:
        parameters = endpoint.parameters.model_validate(arguments)
        try:
            response = await client.post(
                f"/{endpoint.name}", content=parameters.model_dump_json()
            )
        except httpx2.HTTPError as error:
            raise ToolError(f"the query API is unreachable: {error}") from error
        if response.status_code != 200:
            raise ToolError(response.json()["error"])
        return response.text

    call.__name__ = endpoint.name
    call.__doc__ = endpoint.description
    call.__signature__ = endpoint.signature.replace(return_annotation=str)  # type: ignore[attr-defined]
    return call


for endpoint in ENDPOINTS.values():
    server.add_tool(
        _tool(endpoint),
        name=endpoint.name,
        description=endpoint.description,
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=False,
    )
    # The SDK keeps the schema it derived on the tool; there is no public way
    # to hand it a leaner one.
    tool = server._tool_manager.get_tool(endpoint.name)  # pyright: ignore[reportPrivateUsage]
    if tool is not None:
        tool.parameters = _lean(tool.parameters)


def main() -> None:
    """`bpgraph-mcp`: serve until stopped. Only localhost may connect for now;
    remote clients will need their host names allowed."""
    server.run(
        "streamable-http",
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "8080")),
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        ),
    )
