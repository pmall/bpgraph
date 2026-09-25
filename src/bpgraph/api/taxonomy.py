"""Writing the curated viruses, their families, and `:IN_TAXON`."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import TaxonKind
from bpgraph.models import Family, Membership, TaxonLink, Virus

PARENT = """MATCH (child:Taxon {taxon_id: r.child_taxon_id})
MATCH (parent:Taxon {taxon_id: r.parent_taxon_id})
CREATE (child)-[:PARENT]->(parent)"""

IN_TAXON = """MATCH (protein:Protein {id: r.protein_id})
MATCH (taxon:Taxon {taxon_id: r.taxon_id})
CREATE (protein)-[:IN_TAXON]->(taxon)"""


def write_viruses(writer: GraphWriter, viruses: Iterable[Virus]) -> int:
    rows: list[Row] = [
        {"taxon_id": virus.taxon_id, "name": virus.name, "full_name": virus.full_name}
        for virus in dedupe(viruses, key=lambda virus: virus.taxon_id)
    ]
    return writer.create(f"Taxon:{TaxonKind.VIRUS.value}", rows)


def write_families(writer: GraphWriter, families: Iterable[Family]) -> int:
    rows: list[Row] = [
        {"taxon_id": family.taxon_id, "name": family.name}
        for family in dedupe(families, key=lambda family: family.taxon_id)
    ]
    return writer.create(f"Taxon:{TaxonKind.FAMILY.value}", rows)


def write_taxon_links(writer: GraphWriter, links: Iterable[TaxonLink]) -> int:
    rows: list[Row] = [
        {
            "child_taxon_id": link.child_taxon_id,
            "parent_taxon_id": link.parent_taxon_id,
        }
        for link in dedupe(
            links, key=lambda link: (link.child_taxon_id, link.parent_taxon_id)
        )
    ]
    return writer.write(PARENT, rows)


def write_memberships(writer: GraphWriter, memberships: Iterable[Membership]) -> int:
    rows: list[Row] = [
        {"protein_id": membership.protein.id, "taxon_id": membership.taxon_id}
        for membership in dedupe(memberships, key=lambda m: m.protein.id)
    ]
    return writer.write(IN_TAXON, rows)
