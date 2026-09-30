"""Beyond the predefined queries: the schema, and read-only Cypher."""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from bpgraph.api.base import Backend
from bpgraph.query import Row

SCHEMA = Path(__file__).parents[3] / "docs" / "schema.md"


def schema(backend: Backend) -> str:
    """The graph's schema: every label, property and relationship, the keys,
    and what the vaults hold. Read it before writing Cypher."""
    return SCHEMA.read_text()


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
) -> list[Row]:
    """Run one read-only Cypher statement on the live graph, for what no
    predefined query answers. Pass values with `params` rather than inlining
    them. A node comes back as its properties plus `_labels`, an edge as its
    properties plus `_type`: return the properties you need, since protein
    `function` and publication `abstract` are long. Enter proteins through
    `:Protein`, the label whose `id` is indexed: `MATCH (p:Protein) WHERE
    p.id IN $ids WITH p MATCH (p)-…`."""
    return backend.rows(query, **(params or {}))
