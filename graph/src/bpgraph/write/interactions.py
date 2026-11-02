"""Writing the interaction stage: claims, observations, and what supports them.

The shape here is the reification described in docs/schema.md: a description is
a node because it links a pair *and* a publication *and* some peptides, which no
single edge can do. Neither an interaction nor a description has a key: each is
what it links, so an interaction is written in one statement with its two
proteins, its `:INTERACTS_WITH` shortcut and its descriptions. Our curated
descriptions carry their `stable_id`, by which their peptides then find them.
"""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.write.proteins import MATCH

COUNTERS = """n_descriptions: r.n_descriptions, n_publications: r.n_publications,
n_methods: r.n_methods, n_peptides: r.n_peptides"""

SIDE_B: dict[InteractionKind, str] = {
    InteractionKind.HH: "(b:Human {accession: r.b})",
    InteractionKind.VH: "(b:Viral {ncbi_taxon_id: r.b_taxon_id, name: r.b_name})",
}

DESCRIPTIONS = """WITH r, i
UNWIND r.descriptions AS d
MATCH (publication:Publication {pmid: d.pmid})
CREATE (x:Description {method_id: d.method_id, method_name: d.method_name})
CREATE (x)-[:SUPPORTS]->(i)
CREATE (x)-[:REPORTED_IN]->(publication)
FOREACH (_ IN CASE WHEN d.stable_id = '' THEN [] ELSE [1] END |
  SET x:Curated, x.stable_id = d.stable_id)
FOREACH (_ IN CASE WHEN d.stable_id = '' THEN [1] ELSE [] END | SET x:IntAct)
WITH r, count(x) AS described
WHERE described = size(r.descriptions)"""
"""Every description of the row, each `:Curated` with its `stable_id` or
`:IntAct`. A row whose descriptions did not all find their publication is not
counted, so the writer reports it."""

REPORTS = """MATCH (description:Curated {stable_id: r.stable_id})
MATCH (peptide:Peptide {sequence: r.sequence})
CREATE (description)-[:REPORTS]->(peptide)"""


def _interaction_statement(kind: InteractionKind) -> str:
    return (
        "MATCH (a:Human {accession: r.a})\n"
        f"MATCH {SIDE_B[kind]}\n"
        f"CREATE (a)<-[:INVOLVES]-(i:Interaction:{kind.value} {{{COUNTERS}}})"
        "-[:INVOLVES]->(b)\n"
        f"CREATE (a)-[:INTERACTS_WITH {{{COUNTERS}}}]->(b)\n"
        f"{DESCRIPTIONS}"
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
    """Rows of `a`, the human accession, side `b` — an accession for HH,
    `b_taxon_id` and `b_name` for VH — the four counters, and `descriptions`,
    each `pmid`, `method_id`, `method_name` and `stable_id`, `''` for IntAct."""
    return writer.write(_interaction_statement(kind), rows)


def write_reports(writer: GraphWriter, rows: Iterable[Row]) -> int:
    """Rows of a curated description's `stable_id` and a peptide's `sequence`."""
    return writer.write(REPORTS, rows)


def write_peptide_proteins(
    writer: GraphWriter, relation: str, kind: ProteinKind, rows: Iterable[Row]
) -> int:
    """`FROM` the protein a peptide was cut from, `BINDS` one it binds: rows of
    `sequence` and the protein's key. A peptide seen in many reports is linked
    to a protein once."""
    return writer.write(
        "MATCH (peptide:Peptide {sequence: r.sequence})\n"
        f"MATCH {MATCH[kind]}\n"
        f"MERGE (peptide)-[:{relation}]->(protein)",
        rows,
    )
