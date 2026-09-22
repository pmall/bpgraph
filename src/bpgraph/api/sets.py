"""Writing `:ProteinSet` nodes and curated membership."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.models import ProteinSet, SetMembership

MEMBER_OF = """MATCH (protein:Protein {id: r.protein_id})
MATCH (set:ProteinSet {name: r.set_name})
CREATE (protein)-[membership:MEMBER_OF]->(set)
SET membership += r.attributes"""


def write_protein_sets(writer: GraphWriter, sets: Iterable[ProteinSet]) -> int:
    rows: list[Row] = [
        {"name": protein_set.name}
        for protein_set in dedupe(sets, key=lambda protein_set: protein_set.name)
    ]
    return writer.create("ProteinSet", rows)


def write_memberships(writer: GraphWriter, memberships: Iterable[SetMembership]) -> int:
    """Membership metadata is free-form, one level deep. The engine rejects a
    nested map, which the `Attribute` type already rules out."""
    rows: list[Row] = [
        {
            "protein_id": membership.protein.id,
            "set_name": membership.set_name,
            "attributes": dict(membership.attributes),
        }
        for membership in dedupe(memberships, key=lambda m: (m.protein.id, m.set_name))
    ]
    return writer.write(MEMBER_OF, rows)
