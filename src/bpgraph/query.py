"""Query the live graph, read-only: what the MCP server and `bpgraph-query` run.

A statement goes to `bpgraph` with `GRAPH.RO_QUERY`, so the server refuses
anything that writes. Each row is a JSON object keyed by the returned columns.
A node becomes its properties plus `_labels`, an edge its properties plus
`_type`.
"""

import argparse
import json
import sys

from falkordb import Edge, Node, Path
from falkordb.graph import Graph
from redis.exceptions import ResponseError

from bpgraph.client import connect
from bpgraph.config import Config

type Value = None | bool | int | float | str | list[Value] | dict[str, Value]
type Row = dict[str, Value]


def _properties(properties: dict[str, object]) -> dict[str, Value]:
    return {name: plain(v) for name, v in properties.items()}


def plain(value: object) -> Value:
    """A result value as JSON-ready data."""
    match value:
        case Node():
            labels: list[Value] = [str(label) for label in value.labels or ()]
            return {"_labels": labels, **_properties(value.properties)}
        case Edge():
            return {"_type": value.relation, **_properties(value.properties)}
        case Path():
            return {
                "nodes": [plain(n) for n in value.nodes()],
                "edges": [plain(e) for e in value.edges()],
            }
        case dict():
            return {str(k): plain(v) for k, v in value.items()}
        case list() | tuple():
            return [plain(v) for v in value]
        case None | bool() | int() | float() | str():
            return value
        case _:
            return str(value)


def rows(graph: Graph, cypher: str, params: dict[str, object]) -> list[Row]:
    """Run one read-only statement. A statement that writes, or does not
    parse, raises `redis.exceptions.ResponseError`."""
    result = graph.ro_query(cypher, params)
    columns = [str(c[1]) for c in result.header]
    return [
        dict(zip(columns, (plain(v) for v in row), strict=True))
        for row in result.result_set
    ]


def live_graph() -> Graph:
    config = Config.from_env()
    return connect(config).select_graph(config.live_graph)


def main() -> None:
    """`bpgraph-query [--params JSON] [CYPHER]`, the statement read from stdin
    when it is not given."""
    parser = argparse.ArgumentParser(
        prog="bpgraph-query", description="Run a read-only Cypher query on bpgraph."
    )
    parser.add_argument("cypher", nargs="?", help="the statement; stdin if omitted")
    parser.add_argument(
        "--params",
        default="{}",
        help='query parameters as JSON, e.g. \'{"topic": "ferroptosis"}\'',
    )
    args = parser.parse_args()
    cypher: str = args.cypher if args.cypher is not None else sys.stdin.read()
    params: dict[str, object] = json.loads(args.params)

    try:
        result = rows(live_graph(), cypher, params)
    except ResponseError as error:
        sys.exit(f"bpgraph-query: {error}")
    for row in result:
        print(json.dumps(row))
