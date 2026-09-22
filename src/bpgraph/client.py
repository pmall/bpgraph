"""A thin wrapper over the FalkorDB client: batched, parameterized writes."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from falkordb import FalkorDB
from falkordb.graph import Graph

from bpgraph.config import Config

type Row = Mapping[str, object]

BATCH_SIZE = 1000


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

    def run(self, cypher: str) -> None:
        """One statement, no rows — a derivation over what is already there."""
        self.graph.query(cypher)

    def create(self, label: str, rows: Sequence[Row]) -> int:
        """One node per row, its properties taken from the row's own keys.

        `label` may name several, colon-separated (`Protein:Human`). Writing
        the property list out in Cypher as well would be the same list twice,
        free to drift; deriving it from the first row is what keeps a node's
        properties and the record they came from the same thing.
        """
        if not rows:
            return 0
        return self.write(_create(label, rows[0]), rows)

    def write(self, statement: str, rows: Sequence[Row]) -> int:
        """Run `UNWIND $rows AS r <statement>` over rows, in batches.

        Values always travel as parameters. Only labels are ever interpolated
        into a statement, because Cypher cannot parameterize them.
        """
        if not rows:
            return 0
        cypher = f"UNWIND $rows AS r\n{statement}"
        for start in range(0, len(rows), self.batch_size):
            batch = list(rows[start : start + self.batch_size])
            self.graph.query(cypher, {"rows": batch})
        return len(rows)
