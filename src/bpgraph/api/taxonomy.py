"""Writing `:Taxon` nodes, the species-to-family chain, and `:IN_TAXON`."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.models import Taxon, TaxonLink

PARENT = """MATCH (child:Taxon {taxon_id: r.child_taxon_id})
MATCH (parent:Taxon {taxon_id: r.parent_taxon_id})
CREATE (child)-[:PARENT]->(parent)"""

IN_TAXON = """MATCH (protein:Viral)
MATCH (taxon:Taxon {taxon_id: protein.taxon_id})
CREATE (protein)-[:IN_TAXON]->(taxon)"""


def write_taxa(writer: GraphWriter, taxa: Iterable[Taxon]) -> int:
    rows: list[Row] = [
        {"taxon_id": taxon.taxon_id, "name": taxon.name, "rank": taxon.rank}
        for taxon in dedupe(taxa, key=lambda taxon: taxon.taxon_id)
    ]
    return writer.create("Taxon", rows)


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


def link_proteins_to_taxa(writer: GraphWriter) -> None:
    """Derive `:IN_TAXON` from the `taxon_id` every viral protein already carries.

    Run after both proteins and taxa are written. A viral protein whose taxon is
    missing from the export simply gets no edge.
    """
    writer.run(IN_TAXON)
