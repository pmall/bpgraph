"""What every endpoint shares: the backend and the row model."""

from dataclasses import dataclass
from pathlib import Path

from falkordb.graph import Graph
from pydantic import BaseModel, ConfigDict

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
    the question has."""

    model_config = ConfigDict(frozen=True)

    rows: list[R]
    total: int


def whole[R](rows: list[R]) -> Rows[R]:
    """Rows nothing cut."""
    return Rows(rows=rows, total=len(rows))
