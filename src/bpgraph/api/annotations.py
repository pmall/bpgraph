"""Writing `:GoTerm` nodes, the GO ontology edges, and the `:Annotation` nodes
that tie a protein to a term and the publication showing it."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import GoRelation
from bpgraph.models import GoAnnotation, GoEdge, GoTerm

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


def write_go_terms(writer: GraphWriter, terms: Iterable[GoTerm]) -> int:
    rows: list[Row] = [
        {
            "go_id": term.go_id,
            "name": term.name,
            "namespace": term.namespace.value,
            "obsolete": term.obsolete,
        }
        for term in dedupe(terms, key=lambda term: term.go_id)
    ]
    return writer.create("GoTerm", rows)


def write_go_edges(writer: GraphWriter, edges: Iterable[GoEdge]) -> int:
    """`IS_A` and `PART_OF` stay separate edge types so a query can choose which
    closure it wants; the true path rule holds over both."""
    unique = dedupe(
        edges, key=lambda edge: (edge.child_go_id, edge.parent_go_id, edge.relation)
    )
    return sum(
        writer.write(
            _edge_statement(relation),
            [
                {"child_go_id": e.child_go_id, "parent_go_id": e.parent_go_id}
                for e in unique
                if e.relation is relation
            ],
        )
        for relation in GoRelation
    )


def write_go_annotations(
    writer: GraphWriter, annotations: Iterable[GoAnnotation]
) -> int:
    """One node per distinct annotation and publication.

    The qualifier is part of what makes two annotations distinct, because
    `NOT` inverts one; so is the assigning database, because GOA states the
    same term for the same protein from several sources, and picking one of
    them would be picking the provenance.
    """
    rows: list[Row] = [
        {
            "id": annotation.id,
            "protein_id": annotation.protein.id,
            "go_id": annotation.go_id,
            "pmid": annotation.pmid,
            "qualifier": annotation.qualifier,
            "evidence_code": annotation.evidence_code,
            "assigned_by": annotation.assigned_by,
        }
        for annotation in dedupe(annotations, key=lambda a: a.id)
    ]
    return writer.write(ANNOTATION, rows)
