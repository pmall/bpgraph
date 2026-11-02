"""A thin wrapper over the FalkorDB client: batched, parameterized writes."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import batched, chain

from falkordb import FalkorDB
from falkordb.graph import Graph

from bpgraph.config import Config

type Row = Mapping[str, object]

BATCH_SIZE = 1000


class UnmatchedRows(RuntimeError):
    """A write found nothing to attach some of its rows to. The preparation
    guarantees every endpoint exists, so this is a bug, never data."""


def connect(config: Config) -> FalkorDB:
    return FalkorDB(
        host=config.host,
        port=config.port,
        password=config.password or None,
    )


def _create(label: str, properties: Iterable[str]) -> str:
    assignments = ", ".join(f"{name}: r.{name}" for name in properties)
    return f"CREATE (:{label} {{{assignments}}})"


@dataclass(frozen=True, slots=True)
class GraphWriter:
    """Writes to one graph. Never point this at the live graph — a run builds
    into staging and the swap publishes it."""

    graph: Graph
    batch_size: int = BATCH_SIZE

    def create(self, label: str, rows: Iterable[Row]) -> int:
        """One node per row, its properties taken from the row's own keys.

        `label` may name several, colon-separated (`Protein:Human`). Writing
        the property list out in Cypher as well would be the same list twice,
        free to drift; deriving it from the first row is what keeps a node's
        properties and the record they came from the same thing.
        """
        stream = iter(rows)
        first = next(stream, None)
        if first is None:
            return 0
        return self.write(_create(label, first), chain([first], stream))

    def write(self, statement: str, rows: Iterable[Row]) -> int:
        """Run `UNWIND $rows AS r <statement>` over rows, a batch at a time.
        Returns the rows written.

        Every row must match what its statement looks up: a batch whose rows
        do not all come through raises `UnmatchedRows` rather than writing
        less than it was given. Values always travel as parameters. Only
        labels are ever interpolated into a statement, because Cypher cannot
        parameterize them.
        """
        cypher = f"UNWIND $rows AS r\n{statement}\nRETURN count(*)"
        written = 0
        for batch in batched(rows, self.batch_size, strict=False):
            result = self.graph.query(cypher, {"rows": list(batch)})
            count = result.result_set[0][0] if result.result_set else 0
            if count != len(batch):
                raise UnmatchedRows(
                    f"{len(batch) - count} of {len(batch)} rows matched nothing:\n"
                    f"{statement}"
                )
            written += count
        return written
