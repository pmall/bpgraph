"""Writing the curated viruses, their families, and `:IN_TAXON`."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import TaxonKind

PARENT = """MATCH (child:Taxon {ncbi_taxon_id: r.child_taxon_id})
MATCH (parent:Taxon {ncbi_taxon_id: r.parent_taxon_id})
CREATE (child)-[:PARENT]->(parent)"""

IN_TAXON = """MATCH (protein:Viral {ncbi_taxon_id: r.ncbi_taxon_id, name: r.name})
MATCH (taxon:Virus {ncbi_taxon_id: r.ncbi_taxon_id})
CREATE (protein)-[:IN_TAXON]->(taxon)"""


def write_viruses(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `ncbi_taxon_id`, `name`, `full_name`."""
    return writer.create(f"Taxon:{TaxonKind.VIRUS.value}", rows)


def write_families(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `ncbi_taxon_id`, `name`."""
    return writer.create(f"Taxon:{TaxonKind.FAMILY.value}", rows)


def write_taxon_links(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `child_taxon_id`, `parent_taxon_id`."""
    return writer.write(PARENT, rows)


def write_memberships(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of a viral protein's `ncbi_taxon_id` and `name`: its virus is the
    one of that taxon."""
    return writer.write(IN_TAXON, rows)
