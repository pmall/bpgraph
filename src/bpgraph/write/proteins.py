"""Writing `:Protein` nodes, and the publications behind their function text.

A human protein is found by its accession, a viral one by its virus's NCBI
taxon id and its name."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import ProteinKind

NODE_LABELS: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: "Protein:Human",
    ProteinKind.VIRAL: "Protein:Viral",
}

MATCH: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: "(protein:Human {accession: r.accession})",
    ProteinKind.VIRAL: (
        "(protein:Viral {ncbi_taxon_id: r.ncbi_taxon_id, name: r.name})"
    ),
}
"""The pattern finding a row's protein, by the properties that key it."""


def write_proteins(writer: GraphWriter, kind: ProteinKind, rows: Iterable[Row]) -> int:
    """Human rows of `accession`, `name`, `description`, `function`; viral
    rows of `ncbi_taxon_id`, `name`, `function`."""
    return writer.create(NODE_LABELS[kind], rows)


def write_function_citations(
    writer: GraphWriter, kind: ProteinKind, rows: Iterable[Row]
) -> int:
    """Rows of the protein's key and `pmid`."""
    return writer.write(
        f"MATCH {MATCH[kind]}\n"
        "MATCH (publication:Publication {pmid: r.pmid})\n"
        "CREATE (protein)-[:FUNCTION_CITES]->(publication)",
        rows,
    )
