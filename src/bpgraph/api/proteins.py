"""Writing `:Protein` and `:Entry` nodes, and `:ON_ENTRY` between them."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import ProteinKind
from bpgraph.models import Entry, Location, Protein

NODE_LABELS: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: "Protein:Human",
    ProteinKind.VIRAL: "Protein:Viral",
}

ON_ENTRY: dict[ProteinKind, str] = {
    ProteinKind.HUMAN: """MATCH (protein:Protein {id: r.protein_id})
MATCH (entry:Entry {accession: r.accession})
CREATE (protein)-[:ON_ENTRY]->(entry)""",
    ProteinKind.VIRAL: """MATCH (protein:Protein {id: r.protein_id})
MATCH (entry:Entry {accession: r.accession})
CREATE (protein)-[:ON_ENTRY {start: r.start, stop: r.stop}]->(entry)""",
}
"""A human protein is the whole chain of its one entry, so its edge carries no
coordinates; a viral protein's says where on the entry it was excised."""


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


def write_entries(writer: GraphWriter, entries: Iterable[Entry]) -> int:
    rows: list[Row] = [
        {
            "accession": entry.accession,
            "taxon_id": entry.taxon_id,
            "taxon_name": entry.taxon_name,
            "description": entry.description,
        }
        for entry in dedupe(entries, key=lambda entry: entry.accession)
    ]
    return writer.create("Entry", rows)


def write_locations(writer: GraphWriter, locations: Iterable[Location]) -> int:
    unique = dedupe(
        locations,
        key=lambda loc: (loc.protein.id, loc.accession, loc.start, loc.stop),
    )
    return sum(
        writer.write(
            statement,
            [
                {
                    "protein_id": loc.protein.id,
                    "accession": loc.accession,
                    "start": loc.start,
                    "stop": loc.stop,
                }
                for loc in unique
                if loc.protein.kind is kind
            ],
        )
        for kind, statement in ON_ENTRY.items()
    )
