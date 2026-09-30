"""Peptides: short sequences reported sufficient for an interaction, and
directed: derived from one partner, binding the other."""

from typing import Annotated, Literal

from pydantic import Field

from bpgraph.api.base import Backend, Limit, ProteinIds, Record


class PeptideEvidence(Record):
    sequence: str
    length: int
    source_id: str
    source_name: str
    source_virus: str | None
    target_id: str
    target_name: str
    pmids: list[str]
    methods: list[str]


def peptides(
    backend: Backend,
    protein_ids: ProteinIds,
    direction: Annotated[
        Literal["targeting", "derived"],
        Field(
            description="`targeting`: peptides binding these proteins, derived "
            "from their partners. `derived`: peptides cut from these proteins."
        ),
    ] = "targeting",
    limit: Limit = 1000,
) -> list[PeptideEvidence]:
    """Peptides against proteins, or from them, each with its source and
    target protein and the publications and methods reporting it; best
    supported first, then shortest. A peptide is one node whatever it binds:
    its evidence here is for this source and target only."""
    compare = "<>" if direction == "targeting" else "="
    # These proteins are `p`, their partners `o`: which is the source is known
    # before the query runs.
    source, target = ("o", "p") if direction == "targeting" else ("p", "o")
    return [
        PeptideEvidence.model_validate(row)
        for row in backend.rows(
            f"""MATCH (p:Protein) WHERE p.id IN $ids
            WITH p
            MATCH (p)<-[pv:INVOLVES]-(i:Interaction)
            MATCH (i)<-[:SUPPORTS]-(d:Description)-[r:REPORTS]->(x:Peptide)
            WITH p, pv, i, d, r, x WHERE pv.side {compare} r.source_side
            MATCH (i)-[ov:INVOLVES]->(o:Protein)
            WITH p, pv, d, x, o, ov WHERE ov.side <> pv.side
            WITH x, d, {source} AS source, {target} AS target
            MATCH (d)-[:REPORTED_IN]->(b:Publication)
            OPTIONAL MATCH (source)-[:IN_TAXON]->(t:Virus)
            WITH x, source, target, t, collect(DISTINCT b.pmid) AS pmids,
                 collect(DISTINCT d.method_name) AS methods
            RETURN x.sequence AS sequence, x.length AS length,
                   source.id AS source_id, source.name AS source_name,
                   t.name AS source_virus, target.id AS target_id,
                   target.name AS target_name, pmids, methods
            ORDER BY size(pmids) DESC, length, sequence
            LIMIT $limit""",
            ids=protein_ids,
            limit=limit,
        )
    ]


class PeptideReport(Record):
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    interaction_id: str
    description_id: str
    pmid: str
    year: int
    method_name: str


def peptide(
    backend: Backend,
    sequence: Annotated[
        str, Field(min_length=1, description="The peptide's residues.")
    ],
) -> list[PeptideReport]:
    """Every report of one peptide: which protein it came from, which it
    binds, in which publication and by which method, newest first. The same
    sequence seen in two proteins is one peptide, so it may have several
    sources and targets."""
    return [
        PeptideReport.model_validate(row)
        for row in backend.rows(
            """MATCH (x:Peptide {sequence: $sequence})<-[r:REPORTS]-(d:Description)
            MATCH (d)-[:SUPPORTS]->(i:Interaction)
            MATCH (i)-[sv:INVOLVES]->(s:Protein)
            WITH r, d, i, s, sv WHERE sv.side = r.source_side
            MATCH (i)-[tv:INVOLVES]->(t:Protein)
            WITH r, d, i, s, t, tv WHERE tv.side <> r.source_side
            MATCH (d)-[:REPORTED_IN]->(b:Publication)
            RETURN s.id AS source_id, s.name AS source_name, t.id AS target_id,
                   t.name AS target_name, i.id AS interaction_id,
                   d.id AS description_id, b.pmid AS pmid, b.year AS year,
                   d.method_name AS method_name
            ORDER BY year DESC, pmid""",
            sequence=sequence,
        )
    ]
