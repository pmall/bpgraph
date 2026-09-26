"""Writing `:Protein` nodes, and the publications behind their function text."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import ProteinKind
from bpgraph.models import FunctionCitation, Protein

NODE_LABELS: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: "Protein:Human",
    ProteinKind.VIRAL: "Protein:Viral",
}

FUNCTION_CITES = """MATCH (protein:Protein {id: r.protein_id})
MATCH (publication:Publication {pmid: r.pmid})
CREATE (protein)-[:FUNCTION_CITES]->(publication)"""


def _row(protein: Protein) -> Row:
    return {
        "id": protein.id,
        "name": protein.name,
        "description": protein.description,
        "function": protein.function,
    }


def write_proteins(writer: GraphWriter, proteins: Iterable[Protein]) -> int:
    """One statement per kind, because Cypher cannot parameterize a label."""
    unique = dedupe(proteins, key=lambda protein: protein.id)
    return sum(
        writer.create(label, [_row(p) for p in unique if p.kind is kind])
        for kind, label in NODE_LABELS.items()
    )


def write_function_citations(
    writer: GraphWriter, citations: Iterable[FunctionCitation]
) -> int:
    rows: list[Row] = [
        {"protein_id": citation.protein.id, "pmid": citation.pmid}
        for citation in dedupe(citations, key=lambda c: (c.protein.id, c.pmid))
    ]
    return writer.write(FUNCTION_CITES, rows)
