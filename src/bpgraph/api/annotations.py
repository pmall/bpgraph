"""Writing `:GoTerm` nodes, the GO ontology edges, and protein annotations."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import GoRelation
from bpgraph.models import GoAnnotation, GoEdge, GoTerm

ANNOTATED_WITH = """MATCH (protein:Protein {id: r.protein_id})
MATCH (term:GoTerm {go_id: r.go_id})
CREATE (protein)-[:ANNOTATED_WITH {evidence_code: r.evidence_code,
 assigned_by: r.assigned_by, qualifier: r.qualifier}]->(term)"""


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


def _identity(annotation: GoAnnotation) -> tuple[str, str, str, str, str]:
    """Everything an annotation is, which is everything that distinguishes two.

    The qualifier is part of it because `NOT` inverts an annotation: a key that
    left it out would collapse a protein's `involved_in` and `NOT|involved_in`
    rows onto whichever came first. The assigning database is part of it
    because GOA states the same term for the same protein from several sources,
    and picking one of them arbitrarily would be picking the provenance.
    """
    return (
        annotation.protein.id,
        annotation.go_id,
        annotation.qualifier,
        annotation.evidence_code,
        annotation.assigned_by,
    )


def write_go_annotations(
    writer: GraphWriter, annotations: Iterable[GoAnnotation]
) -> int:
    """One edge per distinct annotation. See `_identity` for what distinct means."""
    rows: list[Row] = [
        {
            "protein_id": annotation.protein.id,
            "go_id": annotation.go_id,
            "evidence_code": annotation.evidence_code,
            "assigned_by": annotation.assigned_by,
            "qualifier": annotation.qualifier,
        }
        for annotation in dedupe(annotations, key=_identity)
    ]
    return writer.write(ANNOTATED_WITH, rows)
