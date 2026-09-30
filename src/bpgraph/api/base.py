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
        "publications. 2 is the golden dataset.",
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
