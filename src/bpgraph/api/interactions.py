"""Writing the interaction stage: claims, observations, and what supports them.

The shape here is the reification described in docs/schema.md: a description is
a node because it links two proteins *and* a publication *and* some peptides,
which no single edge can do. An interaction arrives with its counters already
counted, and its `:INTERACTS_WITH` shortcut is written with it.
"""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import InteractionKind

DESCRIPTION = """MATCH (interaction:Interaction {id: r.interaction_id})
MATCH (publication:Publication {pmid: r.pmid})
CREATE (description:Description {id: r.id, intact_id: r.intact_id,
                                 stable_ids: r.stable_ids,
                                 method_id: r.method_id,
                                 method_name: r.method_name})
CREATE (description)-[:SUPPORTS]->(interaction)
CREATE (description)-[:REPORTED_IN]->(publication)"""

REPORTS = """MATCH (description:Description {id: r.description_id})
MATCH (peptide:Peptide {sequence: r.sequence})
CREATE (description)-[:REPORTS {source_side: r.source_side}]->(peptide)"""

COUNTERS = """n_descriptions: r.n_descriptions, n_publications: r.n_publications,
n_peptides: r.n_peptides"""


def _interaction_statement(label: str) -> str:
    return (
        "MATCH (a:Protein {id: r.side_a})\n"
        "MATCH (b:Protein {id: r.side_b})\n"
        f"CREATE (a)<-[:INVOLVES {{side: 'a'}}]-(:Interaction:{label} "
        f"{{id: r.id, {COUNTERS}}})-[:INVOLVES {{side: 'b'}}]->(b)\n"
        f"CREATE (a)-[:INTERACTS_WITH {{interaction_id: r.id, {COUNTERS}}}]->(b)"
    )


def write_publications(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `pmid`, `title`, `year`, `journal`, `abstract`, `authors`."""
    return writer.create("Publication", rows)


def write_peptides(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of `sequence`, `length`: one per distinct sequence."""
    return writer.create("Peptide", rows)


def write_interactions(
    writer: GraphWriter, kind: InteractionKind, rows: Iterable[Row]
) -> int:
    """Rows of `id`, `side_a`, `side_b` and the four counters: the claim, its
    two `:INVOLVES`, and its shortcut from side `a` to side `b`."""
    return writer.write(_interaction_statement(kind.value), rows)


def write_descriptions(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """A description carries its method as properties: a method joins nothing
    else, so it is a fact about the observation, not a node."""
    return writer.write(DESCRIPTION, rows)


def write_reported_peptides(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """`source_side` is what makes a peptide directed, and it belongs here
    rather than on the peptide: the direction is a fact about one observation."""
    return writer.write(REPORTS, rows)
