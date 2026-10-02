"""Writing `:GoTerm` nodes, the GO ontology edges, and the `:Annotation` nodes
that tie a protein to a term and the publications showing it."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import GoRelation

ANNOTATION = """MATCH (protein:Human {accession: r.accession})
MATCH (term:GoTerm {go_id: r.go_id})
CREATE (annotation:Annotation {qualifier: r.qualifier})
CREATE (annotation)-[:ANNOTATES]->(protein)
CREATE (annotation)-[:OF_TERM]->(term)
WITH r, annotation
UNWIND r.publications AS p
MATCH (publication:Publication {pmid: p.pmid})
CREATE (annotation)-[:REPORTED_IN {evidence_codes: p.evidence_codes}]->(publication)
WITH r, count(publication) AS cited
WHERE cited = size(r.publications)"""


def _edge_statement(relation: GoRelation) -> str:
    return (
        "MATCH (child:GoTerm {go_id: r.child_go_id})\n"
        "MATCH (parent:GoTerm {go_id: r.parent_go_id})\n"
        f"CREATE (child)-[:{relation.value}]->(parent)"
    )


def write_go_terms(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `go_id`, `name`, `namespace`."""
    return writer.create("GoTerm", rows)


def write_go_edges(
    writer: GraphWriter, relation: GoRelation, rows: Iterable[Row]
) -> int:
    """`IS_A` and `PART_OF` stay separate edge types so a query can choose which
    closure it wants; the true path rule holds over both."""
    return writer.write(_edge_statement(relation), rows)


def write_go_annotations(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """One node per protein, term and qualifier — the qualifier because `NOT`
    inverts what an annotation states — with an edge to each publication
    showing it, carrying the evidence codes that publication's GOA lines give.
    Rows of `accession`, `go_id`, `qualifier` and `publications`, each `pmid`
    and `evidence_codes`."""
    return writer.write(ANNOTATION, rows)
