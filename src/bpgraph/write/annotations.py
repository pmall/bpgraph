"""Writing `:GoTerm` nodes, the GO ontology edges, and the `:Annotation` nodes
that tie a protein to a term and the publication showing it."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import GoRelation

ANNOTATION = """MATCH (protein:Protein {id: r.protein_id})
MATCH (term:GoTerm {go_id: r.go_id})
MATCH (publication:Publication {pmid: r.pmid})
CREATE (annotation:Annotation {id: r.id, qualifier: r.qualifier,
                               evidence_code: r.evidence_code,
                               assigned_by: r.assigned_by})
CREATE (annotation)-[:ANNOTATES]->(protein)
CREATE (annotation)-[:OF_TERM]->(term)
CREATE (annotation)-[:REPORTED_IN]->(publication)"""


def _edge_statement(relation: GoRelation) -> str:
    return (
        "MATCH (child:GoTerm {go_id: r.child_go_id})\n"
        "MATCH (parent:GoTerm {go_id: r.parent_go_id})\n"
        f"CREATE (child)-[:{relation.value}]->(parent)"
    )


def write_go_terms(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `go_id`, `name`, `namespace`, `obsolete`."""
    return writer.create("GoTerm", rows)


def write_go_edges(
    writer: GraphWriter, relation: GoRelation, rows: Iterable[Row]
) -> int:
    """`IS_A` and `PART_OF` stay separate edge types so a query can choose which
    closure it wants; the true path rule holds over both."""
    return writer.write(_edge_statement(relation), rows)


def write_go_annotations(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """One node per distinct annotation and publication.

    The qualifier is part of what makes two annotations distinct, because
    `NOT` inverts one; so is the assigning database, because GOA states the
    same term for the same protein from several sources, and picking one of
    them would be picking the provenance.
    """
    return writer.write(ANNOTATION, rows)
