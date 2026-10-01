"""What every endpoint shares: the backend, the row model, common parameters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from falkordb.graph import Graph
from pydantic import BaseModel, ConfigDict, Field

from bpgraph.query import Row, rows


@dataclass(frozen=True, slots=True)
class Backend:
    """The live graph and the directory of its published vaults."""

    graph: Graph
    vault: Path

    def rows(self, cypher: str, **params: object) -> list[Row]:
        return rows(self.graph, cypher, params)


class Record(BaseModel):
    """A row an endpoint returns."""

    model_config = ConfigDict(frozen=True)


class Rows[R](BaseModel):
    """What a list endpoint returns: its `rows`, and `total`, how many rows
    the question has, which is more than `rows` when `limit` cut them."""

    model_config = ConfigDict(frozen=True)

    rows: list[R]
    total: int


def whole[R](rows: list[R]) -> Rows[R]:
    """Rows nothing cut."""
    return Rows(rows=rows, total=len(rows))


def paged(
    backend: Backend, body: str, returns: str, grain: str, limit: int, **params: object
) -> Rows[Row]:
    """Run `body`, the query up to its `RETURN`, with `returns`, its `RETURN`
    and `ORDER BY`, cut at `limit`. When `limit` filled the page, `total`
    counts the distinct `grain`, the expression one row is one of."""
    found = backend.rows(f"{body}\n{returns}\nLIMIT $limit", limit=limit, **params)
    if len(found) < limit:
        return whole(found)
    counted = backend.rows(f"{body}\nRETURN count(DISTINCT {grain}) AS total", **params)
    return Rows(rows=found, total=int(str(counted[0]["total"])))


def page[R: Record](
    backend: Backend,
    model: type[R],
    body: str,
    returns: str,
    grain: str,
    limit: int,
    **params: object,
) -> Rows[R]:
    """`paged`, each row read as a `model`."""
    found = paged(backend, body, returns, grain, limit, **params)
    return Rows(rows=[model.model_validate(r) for r in found.rows], total=found.total)


type ProteinKind = Literal["human", "viral"]

KIND = "CASE WHEN {0}:Human THEN 'human' ELSE 'viral' END"
"""The Cypher expression for a protein's kind, `{0}` its variable."""

Limit = Annotated[
    int,
    Field(
        ge=1,
        le=5000,
        description="At most this many rows. A result exactly this long was cut.",
    ),
]
MinPublications = Annotated[
    int,
    Field(
        ge=1,
        description="Keep interactions backed by at least this many distinct "
        "publications; `combine` joins it to `min_methods`. The golden dataset "
        "is 2 publications or 2 methods.",
    ),
]
MinMethods = Annotated[
    int,
    Field(
        ge=1,
        description="Keep interactions observed by at least this many distinct "
        "detection methods; `combine` joins it to `min_publications`.",
    ),
]
Combine = Annotated[
    Literal["and", "or"],
    Field(
        description="Whether an interaction must reach both `min_publications` "
        "and `min_methods`, or either. The golden dataset is `min_publications` "
        "2, `min_methods` 2, `or`."
    ),
]
Accessions = Annotated[
    list[str],
    Field(
        min_length=1,
        description="Human proteins by accession, e.g. a topic's list.",
    ),
]
ProteinIds = Annotated[
    list[str],
    Field(
        min_length=1,
        description="Proteins by id: an accession for a human protein, "
        "`<virus taxon id>:<name>` for a viral one, e.g. `10407:HBx`.",
    ),
]
Family = Annotated[
    str | None, Field(description="A viral family by name, e.g. `Flaviviridae`.")
]
Virus = Annotated[
    str | None,
    Field(description="A curated virus by its short name, e.g. `HCV`, `SARS-CoV-2`."),
]
ViralIds = Annotated[
    list[str] | None,
    Field(description="Viral proteins by id, e.g. `3052230:NS5A`."),
]


def viral_scope(
    family: str | None, virus: str | None, viral_ids: list[str] | None
) -> str:
    """The Cypher condition keeping the viral protein `v` of virus `t` and
    family `f` in scope, or `true` when nothing narrows it. Its parameters
    are `$family`, `$virus` and `$viral_ids`."""
    conditions = [
        condition
        for value, condition in (
            (family, "f.name = $family"),
            (virus, "t.name = $virus"),
            (viral_ids, "v.id IN $viral_ids"),
        )
        if value is not None
    ]
    return " AND ".join(conditions) or "true"


def require_viral_scope(
    family: str | None, virus: str | None, viral_ids: list[str] | None
) -> None:
    if family is None and virus is None and viral_ids is None:
        raise ValueError("give a family, a virus or viral protein ids")


def evidence_level(
    variable: str, min_publications: int, min_methods: int, combine: str
) -> str:
    """The Cypher condition keeping the interaction or shortcut edge
    `variable` at the evidence level. Its parameters are `$min_publications`
    and `$min_methods`. Under `or`, a threshold left at 1 is reached by every
    interaction, so the other would filter nothing: that is refused."""
    if combine == "or" and min(min_publications, min_methods) == 1 < max(
        min_publications, min_methods
    ):
        raise ValueError(
            "under `or`, a threshold of 1 keeps every interaction: raise both, "
            "or use `and`"
        )
    return (
        f"({variable}.n_publications >= $min_publications {combine.upper()} "
        f"{variable}.n_methods >= $min_methods)"
    )
