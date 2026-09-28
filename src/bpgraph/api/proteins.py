"""Writing `:Protein` nodes, and the publications behind their function text."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import ProteinKind

NODE_LABELS: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: "Protein:Human",
    ProteinKind.VIRAL: "Protein:Viral",
}

FUNCTION_CITES = """MATCH (protein:Protein {id: r.protein_id})
MATCH (publication:Publication {pmid: r.pmid})
CREATE (protein)-[:FUNCTION_CITES]->(publication)"""


def write_proteins(writer: GraphWriter, kind: ProteinKind, rows: Iterable[Row]) -> int:
    """Rows of `id`, `name`, `description`, `function`."""
    return writer.create(NODE_LABELS[kind], rows)


def write_function_citations(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `protein_id`, `pmid`."""
    return writer.write(FUNCTION_CITES, rows)
