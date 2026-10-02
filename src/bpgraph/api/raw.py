"""Beyond the predefined queries: the schema, and read-only Cypher."""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from bpgraph.api.base import Backend, Rows, whole
from bpgraph.query import Row

SCHEMA = (Path(__file__).parents[1] / "guide" / "schema.md").read_text()


def schema(backend: Backend) -> str:
    """The graph's labels, properties and relationships, with what is indexed,
    then the rules for Cypher that runs fast and worked examples. Read it
    before writing `cypher`."""
    return SCHEMA


def cypher(
    backend: Backend,
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="One read-only Cypher statement, values as `$name`.",
        ),
    ],
    params: Annotated[
        dict[str, object] | None, Field(description="The values of `$name`.")
    ] = None,
) -> Rows[Row]:
    """Run one read-only Cypher statement on the live graph, for what no
    predefined tool answers."""
    return whole(backend.rows(query, **(params or {})))
