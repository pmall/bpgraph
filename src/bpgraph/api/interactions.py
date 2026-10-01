"""Interactions: partners, VH and HH sets, the neighbourhood of a protein set,
coverage by family, and the evidence behind a claim.

A filtered `MATCH` is closed with `WITH` before the next `MATCH` extends it,
as docs/development.md asks.
"""

from typing import Annotated, Literal

from pydantic import Field

from bpgraph import vault
from bpgraph.api.base import (
    KIND,
    Accessions,
    Backend,
    Combine,
    Family,
    Limit,
    MinMethods,
    MinPublications,
    ProteinKind,
    Record,
    Rows,
    ViralIds,
    Virus,
    evidence_level,
    page,
    paged,
    require_viral_scope,
    viral_scope,
    whole,
)
from bpgraph.api.names import check_interactions, check_proteins, check_scope


class Partner(Record):
    interaction_id: str
    id: str
    name: str
    description: str
    kind: ProteinKind
    virus: str | None
    n_publications: int
    n_methods: int
    n_descriptions: int
    n_peptides: int


def partners(
    backend: Backend,
    protein_id: Annotated[str, Field(description="A protein id, e.g. `P36969`.")],
    kind: Annotated[
        ProteinKind | None, Field(description="Keep human or viral partners only.")
    ] = None,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
    limit: Limit = 500,
) -> Rows[Partner]:
    """A protein's interaction partners, best supported first, with the
    counters of each interaction: distinct publications and detection
    methods, descriptions (single observations) and peptides. A homodimer is
    left out; `proteins` says whether a protein binds itself."""
    keep = {"human": "AND q:Human", "viral": "AND q:Viral", None: ""}[kind]
    level = evidence_level("e", min_publications, min_methods, combine)
    check_proteins(backend, [protein_id])
    return page(
        backend,
        Partner,
        f"""MATCH (p:Protein {{id: $protein_id}})-[e:INTERACTS_WITH]-(q:Protein)
        WITH e, p, q
        WHERE q <> p AND {level} {keep}
        OPTIONAL MATCH (q)-[:IN_TAXON]->(t:Virus)""",
        f"""RETURN e.interaction_id AS interaction_id, q.id AS id, q.name AS name,
               q.description AS description, {KIND.format("q")} AS kind,
               t.name AS virus, e.n_publications AS n_publications,
               e.n_methods AS n_methods, e.n_descriptions AS n_descriptions,
               e.n_peptides AS n_peptides
        ORDER BY n_publications DESC, n_methods DESC, n_descriptions DESC, name""",
        "e.interaction_id",
        limit,
        protein_id=protein_id,
        min_publications=min_publications,
        min_methods=min_methods,
    )


class VHInteraction(Record):
    interaction_id: str
    human_id: str
    human_name: str
    viral_id: str
    viral_name: str
    virus: str
    family: str | None
    n_publications: int
    n_methods: int
    n_descriptions: int
    n_peptides: int
    methods: list[str]


def vh_interactions(
    backend: Backend,
    accessions: Annotated[
        list[str] | None,
        Field(description="Keep interactions with these human proteins, e.g. a topic."),
    ] = None,
    family: Family = None,
    virus: Virus = None,
    viral_ids: ViralIds = None,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
    limit: Limit = 1000,
) -> Rows[VHInteraction]:
    """Virus–human interactions, narrowed by human proteins, by viral family,
    virus or viral proteins, or any combination; at least one is needed. Each
    comes with its counters and the distinct detection methods behind it.
    Evidence is per curated viral protein: never add counters across viral
    proteins or viruses to push a pair over a threshold."""
    if accessions is None:
        require_viral_scope(family, virus, viral_ids)
    human = "WHERE h.id IN $accessions" if accessions is not None else ""
    level = evidence_level("i", min_publications, min_methods, combine)
    check_scope(backend, family, virus, viral_ids)
    if accessions is not None:
        check_proteins(backend, accessions, "human")
    return page(
        backend,
        VHInteraction,
        f"""MATCH (v:Viral)-[:IN_TAXON]->(t:Virus)
        OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
        WITH v, t, f WHERE {viral_scope(family, virus, viral_ids)}
        MATCH (v)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(h:Human)
        WITH v, t, f, i, h {human}
        WITH v, t, f, i, h WHERE {level}""",
        """MATCH (i)<-[:SUPPORTS]-(d:Description)
        RETURN i.id AS interaction_id, h.id AS human_id, h.name AS human_name,
               v.id AS viral_id, v.name AS viral_name, t.name AS virus,
               f.name AS family, i.n_publications AS n_publications,
               i.n_methods AS n_methods, i.n_descriptions AS n_descriptions,
               i.n_peptides AS n_peptides,
               collect(DISTINCT d.method_name) AS methods
        ORDER BY n_publications DESC, n_methods DESC, n_descriptions DESC,
                 interaction_id""",
        "i",
        limit,
        accessions=accessions,
        family=family,
        virus=virus,
        viral_ids=viral_ids,
        min_publications=min_publications,
        min_methods=min_methods,
    )


class HHInteraction(Record):
    interaction_id: str
    a_id: str
    a_name: str
    b_id: str
    b_name: str
    n_publications: int
    n_methods: int
    n_descriptions: int


def hh_interactions(
    backend: Backend,
    accessions: Accessions,
    around: Annotated[
        bool,
        Field(
            description="Also the interactions from the set to proteins outside "
            "it; otherwise only those within the set."
        ),
    ] = False,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
    limit: Limit = 1000,
) -> Rows[HHInteraction]:
    """Human–human interactions within a set of human proteins, such as a
    topic, or around it too. Side `a` is always in the set. Homodimers are
    left out. Where a description comes from, IntAct or our curation, is in
    `evidence`."""
    outside = "NOT q.id IN $accessions OR " if around else ""
    inside = "" if around else "AND q.id IN $accessions"
    level = evidence_level("e", min_publications, min_methods, combine)
    check_proteins(backend, accessions, "human")
    return page(
        backend,
        HHInteraction,
        f"""MATCH (p:Protein) WHERE p.id IN $accessions AND p:Human
        WITH p
        MATCH (p)-[e:INTERACTS_WITH]-(q:Human)
        WITH p, e, q
        WHERE q <> p AND {level} {inside}
          AND ({outside}p.id < q.id)""",
        """RETURN e.interaction_id AS interaction_id, p.id AS a_id, p.name AS a_name,
               q.id AS b_id, q.name AS b_name, e.n_publications AS n_publications,
               e.n_methods AS n_methods, e.n_descriptions AS n_descriptions
        ORDER BY n_publications DESC, n_methods DESC, n_descriptions DESC,
                 interaction_id""",
        "e.interaction_id",
        limit,
        accessions=accessions,
        min_publications=min_publications,
        min_methods=min_methods,
    )


class Neighbour(Record):
    id: str
    name: str
    description: str
    n_set_partners: int
    set_partners: list[str]
    best_publications: int
    best_methods: int


def neighbours(
    backend: Backend,
    accessions: Accessions,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
    limit: Limit = 200,
) -> Rows[Neighbour]:
    """Human proteins outside a set that interact with it, ranked by how many
    of the set's proteins they bind, then by their best support. The first
    shell of a topic: regulators, ligases, transporters' partners, and the
    candidates for adding to the topic."""
    level = evidence_level("e", min_publications, min_methods, combine)
    check_proteins(backend, accessions, "human")
    return page(
        backend,
        Neighbour,
        f"""MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
        WITH h
        MATCH (h)-[e:INTERACTS_WITH]-(n:Human)
        WITH h, e, n
        WHERE n <> h AND NOT n.id IN $accessions
          AND {level}""",
        """RETURN n.id AS id, n.name AS name, n.description AS description,
               count(DISTINCT h) AS n_set_partners,
               collect(DISTINCT h.name) AS set_partners,
               max(e.n_publications) AS best_publications,
               max(e.n_methods) AS best_methods
        ORDER BY n_set_partners DESC, best_publications DESC, best_methods DESC,
                 name""",
        "n",
        limit,
        accessions=accessions,
        min_publications=min_publications,
        min_methods=min_methods,
    )


class IndirectReach(Record):
    viral_id: str
    viral_name: str
    virus: str
    via_id: str
    via_name: str
    target_id: str
    target_name: str
    vh_publications: int
    vh_methods: int
    hh_publications: int
    hh_methods: int


def indirect_reach(
    backend: Backend,
    accessions: Accessions,
    family: Family = None,
    virus: Virus = None,
    viral_ids: ViralIds = None,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
    limit: Limit = 1000,
) -> Rows[IndirectReach]:
    """Viral proteins reaching a set of human proteins through one human
    protein outside it: viral → via (VH) and via → target (HH), each hop at
    the evidence level. Narrow the viral side by family, virus or viral
    proteins; one is needed. A via protein in the set is a direct target, and
    is left out."""
    require_viral_scope(family, virus, viral_ids)
    vh = evidence_level("vh", min_publications, min_methods, combine)
    hh = evidence_level("hh", min_publications, min_methods, combine)
    check_scope(backend, family, virus, viral_ids)
    check_proteins(backend, accessions, "human")
    return page(
        backend,
        IndirectReach,
        f"""MATCH (v:Viral)-[:IN_TAXON]->(t:Virus)
        OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
        WITH v, t, f WHERE {viral_scope(family, virus, viral_ids)}
        MATCH (v)-[vh:INTERACTS_WITH]-(m:Human)
        WITH v, t, vh, m
        WHERE {vh} AND NOT m.id IN $accessions
        MATCH (m)-[hh:INTERACTS_WITH]-(h:Human)
        WITH v, t, vh, m, hh, h
        WHERE h.id IN $accessions AND {hh}""",
        """RETURN v.id AS viral_id, v.name AS viral_name, t.name AS virus,
               m.id AS via_id, m.name AS via_name, h.id AS target_id,
               h.name AS target_name, vh.n_publications AS vh_publications,
               vh.n_methods AS vh_methods, hh.n_publications AS hh_publications,
               hh.n_methods AS hh_methods
        ORDER BY vh_publications + hh_publications DESC, viral_name, via_name""",
        "[vh.interaction_id, hh.interaction_id]",
        limit,
        accessions=accessions,
        family=family,
        virus=virus,
        viral_ids=viral_ids,
        min_publications=min_publications,
        min_methods=min_methods,
    )


class Coverage(Record):
    group: str
    family: str | None
    n_targets: int
    targets: list[str]
    n_viral_proteins: int
    n_interactions: int
    n_human_targets: int


def coverage(
    backend: Backend,
    accessions: Accessions,
    by: Annotated[
        Literal["family", "virus"], Field(description="Group by family or by virus.")
    ] = "family",
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
) -> Rows[Coverage]:
    """How each viral family, or each virus, reaches a set of human proteins:
    the set's proteins it targets, by which viral proteins and interactions,
    beside `n_human_targets`, every human protein it targets at the evidence
    level, which is the background for asking whether it hits the set more
    than its overall reach predicts. Only groups reaching the set are
    returned. Grouped by family, viruses with no family fall out."""
    group = "f.name" if by == "family" else "t.name"
    keep = "WHERE f IS NOT NULL" if by == "family" else ""
    level = evidence_level("e", min_publications, min_methods, combine)
    check_proteins(backend, accessions, "human")
    return whole(
        [
            Coverage.model_validate(row)
            for row in backend.rows(
                f"""MATCH (v:Viral)-[:IN_TAXON]->(t:Virus)
                OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
                WITH v, t, f {keep}
                MATCH (v)-[e:INTERACTS_WITH]-(h:Human)
                WITH {group} AS group, f.name AS family, v, e, h,
                     h.id IN $accessions AS in_set
                WHERE {level}
                WITH group, family,
                     count(DISTINCT h) AS n_human_targets,
                     collect(DISTINCT CASE WHEN in_set THEN h.name END) AS targets,
                     count(DISTINCT CASE WHEN in_set THEN v END) AS n_viral_proteins,
                     count(DISTINCT CASE WHEN in_set THEN e.interaction_id END)
                         AS n_interactions
                WHERE size(targets) > 0
                RETURN group, family, size(targets) AS n_targets, targets,
                       n_viral_proteins, n_interactions, n_human_targets
                ORDER BY n_targets DESC, group""",
                accessions=accessions,
                min_publications=min_publications,
                min_methods=min_methods,
            )
        ]
    )


class Peptide(Record):
    sequence: str
    source_id: str


class Evidence(Record):
    interaction_id: str
    description_id: str
    pmid: str
    year: int
    title: str
    method_id: str
    method_name: str
    source: Literal["intact", "curated", "both"]
    intact_id: str
    stable_ids: list[str]
    peptides: list[Peptide]
    viral_accession: str | None


def evidence(
    backend: Backend,
    interaction_ids: Annotated[
        list[str],
        Field(min_length=1, description="Interaction ids, e.g. `P36969|3052230:NS5A`."),
    ],
    limit: Limit = 1000,
) -> Rows[Evidence]:
    """The descriptions behind interactions, newest first: each is one
    observation, with its publication, detection method, where it comes from
    (IntAct, our curation, or both independently), its peptides with the
    protein each came from, and for a VH description the viral UniProt entry
    it observed. Read the abstracts with `publications`."""
    check_interactions(backend, interaction_ids)
    found = paged(
        backend,
        """MATCH (i:Interaction) WHERE i.id IN $ids
        WITH i
        MATCH (i)<-[:SUPPORTS]-(d:Description)
        MATCH (d)-[:REPORTED_IN]->(b:Publication)""",
        """OPTIONAL MATCH (d)-[r:REPORTS]->(x:Peptide)
        OPTIONAL MATCH (i)-[s:INVOLVES]->(source:Protein)
        WHERE s.side = r.source_side
        WITH i, d, b, collect(CASE WHEN x IS NULL THEN NULL
                                   ELSE {sequence: x.sequence, source_id: source.id}
                              END) AS peptides
        RETURN i.id AS interaction_id, d.id AS description_id, b.pmid AS pmid,
               b.year AS year, b.title AS title, d.method_id AS method_id,
               d.method_name AS method_name,
               CASE WHEN d.intact_id = '' THEN 'curated'
                    WHEN size(d.stable_ids) = 0 THEN 'intact'
                    ELSE 'both' END AS source,
               d.intact_id AS intact_id, d.stable_ids AS stable_ids, peptides
        ORDER BY interaction_id, year DESC, pmid""",
        "d",
        limit,
        ids=interaction_ids,
    )
    rows = found.rows
    entries = (
        vault.observed_entries(
            backend.vault, [str(row["description_id"]) for row in rows]
        )
        if rows
        else {}
    )
    return Rows(
        rows=[
            Evidence.model_validate(
                {**row, "viral_accession": entries.get(str(row["description_id"]))}
            )
            for row in rows
        ],
        total=found.total,
    )
