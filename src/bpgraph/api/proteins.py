"""Writing `:Protein` nodes."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import ProteinKind
from bpgraph.models import Protein

NODE_LABELS: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: "Protein:Human",
    ProteinKind.VIRAL: "Protein:Viral",
}


def _row(protein: Protein) -> Row:
    return {
        "id": protein.id,
        "accession": protein.accession,
        "start": protein.start,
        "stop": protein.stop,
        "name": protein.name,
        "description": protein.description,
        "function": protein.function,
        "taxon_id": protein.taxon_id,
        "taxon_name": protein.taxon_name,
    }


def write_proteins(writer: GraphWriter, proteins: Iterable[Protein]) -> int:
    """One statement per kind, because Cypher cannot parameterize a label."""
    unique = dedupe(proteins, key=lambda protein: protein.id)
    return sum(
        writer.create(label, [_row(p) for p in unique if p.kind is kind])
        for kind, label in NODE_LABELS.items()
    )
