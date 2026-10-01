"""The MCP server, `bpgraph-mcp`: the only thing consumers see.

Each endpoint of the query API is a tool of the same name, signature and
description, which forwards its arguments to the API at `BPGRAPH_API` and
hands back its answer. The server reaches neither the graph nor the vaults
itself. It serves streamable HTTP at `/mcp`, on `MCP_HOST` and `MCP_PORT`.
"""

import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from bpgraph.api.endpoints import ENDPOINTS, Endpoint

INSTRUCTIONS = """\
bpgraph is a knowledge graph of protein-protein interactions, human-human \
and virus-human. Every interaction is backed by the publications that report \
it, with their titles and abstracts; every human protein of Swiss-Prot is \
there, with its UniProt function text and experimental GO annotations of \
what it does (biological process and molecular function), each tied to the \
publication showing it; a viral protein is a curated one, such as HBx of HBV, \
pooled over the strains it was observed on, under its curated virus and that \
virus's family. Sequences are kept apart, one protein at a time. \
Start with the predefined tools; they know the graph's pitfalls, such as \
peptide direction and NOT annotations. Use `cypher` for what they do not \
answer, after reading `schema`. The counters on an interaction are its \
evidence, and the text is where the insight is: read abstracts and function \
text once a question is narrowed down. \
A list comes back as `rows` and `total`, how many rows the question has \
whatever `limit` kept. A result larger than `max_tokens` (25,000 by default, \
estimated at three characters of JSON per token) is refused with its size \
and row counts, never cut: narrow the question, lower `limit` or raise \
`max_tokens`. An unknown family, virus, protein, GO term, pmid, interaction \
or peptide is an error naming the closest known ones.\
"""

API = os.environ.get("BPGRAPH_API", "http://127.0.0.1:8000")

server = MCPServer(name="bpgraph", instructions=INSTRUCTIONS)
client = httpx2.AsyncClient(base_url=API, timeout=300)


def _tool(endpoint: Endpoint) -> Callable[..., Awaitable[Any]]:
    """A function with the endpoint's signature, calling it over HTTP. Its
    text is the API's compact JSON, the size `max_tokens` was checked against,
    rather than the indented JSON the SDK would write; the same value is its
    structured content."""

    async def call(**arguments: Any) -> CallToolResult:
        parameters = endpoint.parameters.model_validate(arguments)
        try:
            response = await client.post(
                f"/{endpoint.name}", content=parameters.model_dump_json()
            )
        except httpx2.HTTPError as error:
            raise ToolError(f"the query API is unreachable: {error}") from error
        if response.status_code != 200:
            raise ToolError(response.json()["error"])
        value = endpoint.result.validate_json(response.content)
        if isinstance(value, BaseModel):
            return CallToolResult(
                content=[TextContent(type="text", text=response.text)],
                structured_content=value.model_dump(mode="json"),
            )
        return CallToolResult(
            content=[TextContent(type="text", text=str(value))],
            structured_content={"result": value},
        )

    call.__name__ = endpoint.name
    call.__doc__ = endpoint.description
    call.__signature__ = endpoint.signature  # type: ignore[attr-defined]
    return call


for endpoint in ENDPOINTS.values():
    server.add_tool(
        _tool(endpoint),
        name=endpoint.name,
        description=endpoint.description,
        annotations=ToolAnnotations(read_only_hint=True),
    )


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
