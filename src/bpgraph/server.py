"""The MCP server: how agents explore the live graph.

`bpgraph-mcp` serves streamable HTTP at `/mcp`, on the host and port in
`MCP_HOST` and `MCP_PORT`. Every tool is read-only: it runs through
`bpgraph.query`, whose statements the database itself refuses to let write.
"""

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from redis.exceptions import ResponseError

from bpgraph.query import Row, live_graph, rows

INSTRUCTIONS = """\
bpgraph is a FalkorDB knowledge graph of protein-protein interactions, \
human-human and virus-human. Every interaction is backed by the publications \
that report it, with their titles and abstracts; every human protein of \
Swiss-Prot is there, with its UniProt function text and experimental GO \
annotations, and each annotation and function text links to the publications \
behind it; a viral protein is a curated one, such as HBx of HBV, pooled over \
the strains it was observed on, and links to its curated virus and that \
virus's family; topics are curated lists of human proteins, such as \
ferroptosis. \
Query it in Cypher, read-only. The counters on an Interaction are its \
evidence, and the text is where the insight is: read abstracts and function \
text once a question is narrowed down.\
"""

server = MCPServer(name="bpgraph", instructions=INSTRUCTIONS)
graph = live_graph()


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def query(cypher: str, params: dict[str, object] | None = None) -> list[Row]:
    """Run one read-only Cypher statement on the live graph.

    Pass values as `$name` placeholders with `params` rather than inlining
    them. Each row is an object keyed by the returned columns; a node comes
    back as its properties plus `_labels`, an edge as its properties plus
    `_type`. Return the properties you need rather than whole nodes: protein
    `function` and publication `abstract` are long.
    """
    try:
        return rows(graph, cypher, params or {})
    except ResponseError as error:
        raise ToolError(str(error)) from error


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
