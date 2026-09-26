"""Writing the interaction stage: claims, observations, and what supports them.

The shape here is the reification described in docs/schema.md: a description is
a node because it links two proteins *and* a publication *and* a method *and*
some peptides, which no single edge can do.
"""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.enums import InteractionKind
from bpgraph.models import Description, Method, Publication

DESCRIPTION = """MATCH (interaction:Interaction {id: r.interaction_id})
MATCH (publication:Publication {pmid: r.pmid})
MATCH (method:Method {psimi_id: r.psimi_id})
CREATE (description:Description {id: r.id, intact_id: r.intact_id,
                                 stable_ids: r.stable_ids})
CREATE (description)-[:SUPPORTS]->(interaction)
CREATE (description)-[:REPORTED_IN]->(publication)
CREATE (description)-[:DETECTED_BY]->(method)"""

REPORTS = """MATCH (description:Description {id: r.description_id})
MATCH (peptide:Peptide {sequence: r.sequence})
CREATE (description)-[:REPORTS {source_side: r.source_side}]->(peptide)"""

INTERACTION_COUNTERS = """MATCH (interaction:Interaction)<-[:SUPPORTS]-(d:Description)
OPTIONAL MATCH (d)-[:REPORTED_IN]->(publication:Publication)
OPTIONAL MATCH (d)-[:DETECTED_BY]->(method:Method)
OPTIONAL MATCH (d)-[:REPORTS]->(peptide:Peptide)
WITH interaction,
     count(DISTINCT d) AS n_descriptions,
     count(DISTINCT publication) AS n_publications,
     count(DISTINCT method.class) AS n_methods,
     count(DISTINCT peptide) AS n_peptides
SET interaction.n_descriptions = n_descriptions,
    interaction.n_publications = n_publications,
    interaction.n_methods = n_methods,
    interaction.n_peptides = n_peptides"""


def _interaction_statement(label: str) -> str:
    return (
        "MATCH (a:Protein {id: r.side_a})\n"
        "MATCH (b:Protein {id: r.side_b})\n"
        f"CREATE (a)<-[:INVOLVES {{side: 'a'}}]-(:Interaction:{label} {{id: r.id}})"
        "-[:INVOLVES {side: 'b'}]->(b)"
    )


def _claim_row(identity: str, description: Description) -> Row:
    side_a, side_b = description.partners
    return {"id": identity, "side_a": side_a.id, "side_b": side_b.id}


def write_publications(writer: GraphWriter, publications: Iterable[Publication]) -> int:
    rows: list[Row] = [
        {
            "pmid": publication.pmid,
            "title": publication.title,
            "year": publication.year,
            "journal": publication.journal,
            "abstract": publication.abstract,
            "authors": list(publication.authors),
        }
        for publication in dedupe(publications, key=lambda p: p.pmid)
    ]
    return writer.create("Publication", rows)


def write_methods(writer: GraphWriter, methods: Iterable[Method]) -> int:
    rows: list[Row] = [
        {"psimi_id": method.psimi_id, "name": method.name, "class": method.method_class}
        for method in dedupe(methods, key=lambda m: m.psimi_id)
    ]
    return writer.create("Method", rows)


def write_peptides(writer: GraphWriter, descriptions: Iterable[Description]) -> int:
    """One node per unique sequence, however many descriptions report it."""
    peptides = {
        reported.peptide.sequence: reported.peptide
        for description in descriptions
        for reported in description.peptides
    }
    rows: list[Row] = [
        {"sequence": sequence, "length": peptides[sequence].length}
        for sequence in sorted(peptides)
    ]
    return writer.create("Peptide", rows)


def write_interactions(writer: GraphWriter, descriptions: Iterable[Description]) -> int:
    """Interactions are derived from descriptions — the claim behind the rows.

    Many descriptions collapse onto one interaction, which is the point: the
    counters over them are the confidence signal. They cannot go through
    `dedupe`, which insists records sharing a key be identical; here they
    differ by design, and the first one to name a claim describes it fully.
    """
    claims: dict[str, Description] = {}
    for description in descriptions:
        claims.setdefault(description.interaction_id, description)
    return sum(
        writer.write(
            _interaction_statement(kind.value),
            [_claim_row(i, d) for i, d in claims.items() if d.interaction_kind is kind],
        )
        for kind in InteractionKind
    )


def write_descriptions(writer: GraphWriter, descriptions: Iterable[Description]) -> int:
    rows: list[Row] = [
        {
            "id": description.id,
            "intact_id": description.intact_id,
            "stable_ids": list(description.stable_ids),
            "interaction_id": description.interaction_id,
            "pmid": description.pmid,
            "psimi_id": description.psimi_id,
        }
        for description in dedupe(descriptions, key=lambda d: d.id)
    ]
    return writer.write(DESCRIPTION, rows)


def write_reported_peptides(
    writer: GraphWriter, descriptions: Iterable[Description]
) -> int:
    """`source_side` is what makes a peptide directed, and it belongs here
    rather than on the peptide: the direction is a fact about one observation."""
    rows: list[Row] = [
        {
            "description_id": description.id,
            "sequence": reported.peptide.sequence,
            "source_side": description.source_side(reported).value,
        }
        for description in descriptions
        for reported in description.peptides
    ]
    return writer.write(REPORTS, rows)


def update_interaction_counters(writer: GraphWriter) -> None:
    """The confidence signal: distinct publications and method classes behind
    a claim, and whether any peptide came out of it. One pass, nothing
    incremental."""
    writer.run(INTERACTION_COUNTERS)
