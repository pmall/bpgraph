"""Orientation: what the graph holds, its viruses, and finding proteins."""

from typing import Annotated

from pydantic import Field

from bpgraph.api.base import (
    KIND,
    Backend,
    Combine,
    Family,
    MinMethods,
    MinPublications,
    ProteinIds,
    ProteinKind,
    Record,
    Rows,
    Virus,
    evidence_level,
    viral_scope,
    whole,
)
from bpgraph.api.names import check_proteins, check_scope

LABELS = (
    "Human",
    "Viral",
    "Virus",
    "Family",
    "HH",
    "VH",
    "Description",
    "Publication",
    "Annotation",
    "GoTerm",
    "Peptide",
)


class LabelCount(Record):
    label: str
    count: int


def overview(backend: Backend) -> Rows[LabelCount]:
    """How many nodes of each kind the live graph holds: human and viral
    proteins, viruses and families, HH and VH interactions, descriptions,
    publications, GO annotations and terms, peptides."""
    return whole(
        [
            LabelCount.model_validate(
                {
                    "label": label,
                    **backend.rows(f"MATCH (n:{label}) RETURN count(n) AS count")[0],
                }
            )
            for label in LABELS
        ]
    )


class VirusRecord(Record):
    taxon_id: int
    name: str
    full_name: str
    family: str | None
    n_proteins: int
    n_interactions: int
    n_human_targets: int


def viruses(
    backend: Backend,
    family: Family = None,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
) -> Rows[VirusRecord]:
    """The curated viruses, with their family and how much of the human
    interactome they reach at the evidence level: viral proteins, VH
    interactions and distinct human targets. A virus with no family has
    `family` null. The counts are the background a topic's coverage is
    read against: a much-studied virus reaches more of everything."""
    keep = "WHERE f.name = $family" if family is not None else ""
    level = evidence_level("e", min_publications, min_methods, combine)
    check_scope(backend, family, None, None)
    return whole(
        [
            VirusRecord.model_validate(row)
            for row in backend.rows(
                f"""MATCH (t:Virus)
            OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
            WITH t, f {keep}
            OPTIONAL MATCH (t)<-[:IN_TAXON]-(v:Viral)
            OPTIONAL MATCH (v)-[e:INTERACTS_WITH]-(h:Human)
            WHERE {level}
            RETURN t.taxon_id AS taxon_id, t.name AS name, t.full_name AS full_name,
                   f.name AS family, count(DISTINCT v) AS n_proteins,
                   count(DISTINCT e.interaction_id) AS n_interactions,
                   count(DISTINCT h) AS n_human_targets
            ORDER BY n_interactions DESC, name""",
                family=family,
                min_publications=min_publications,
                min_methods=min_methods,
            )
        ]
    )


class ProteinRecord(Record):
    id: str
    name: str
    description: str
    kind: ProteinKind
    virus: str | None
    family: str | None


DESCRIBE = f"""OPTIONAL MATCH (p)-[:IN_TAXON]->(t:Virus)
OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
WITH p, t, f
RETURN p.id AS id, p.name AS name, p.description AS description,
       {KIND.format("p")} AS kind, t.name AS virus, f.name AS family"""
"""Describe the protein `p`: what every protein record starts with."""


class ProteinMatch(ProteinRecord):
    query: str


def find_proteins(
    backend: Backend,
    names: Annotated[
        list[str],
        Field(
            min_length=1,
            description="Gene symbols (`GPX4`), viral protein names (`NS5A`), "
            "accessions or viral protein ids. Case-sensitive.",
        ),
    ],
    virus: Virus = None,
) -> Rows[ProteinMatch]:
    """Resolve names to proteins, each match with the `query` it answers. A
    name matches a protein's `name` or its `id` exactly, and case matters:
    EBV has both `BARF1` and `BaRF1`. A viral name such as `NS5A` is shared by
    many viruses; give `virus` to keep one. A query with no row matched
    nothing."""
    check_scope(backend, None, virus, None)
    rows = backend.rows(
        """UNWIND $names AS query
        MATCH (p:Protein {name: query})
        RETURN query, p.id AS id
        UNION
        UNWIND $names AS query
        MATCH (p:Protein {id: query})
        RETURN query, p.id AS id""",
        names=names,
    )
    cards = {
        card.id: card
        for card in (
            ProteinRecord.model_validate(row)
            for row in backend.rows(
                f"""MATCH (p:Protein) WHERE p.id IN $ids
                WITH p
                {DESCRIBE}""",
                ids=list({str(row["id"]) for row in rows}),
            )
        )
    }
    matches = (
        ProteinMatch.model_validate(
            {**cards[str(row["id"])].model_dump(), "query": row["query"]}
        )
        for row in rows
    )
    return whole([m for m in matches if virus is None or m.virus == virus])


class ProteinCard(ProteinRecord):
    function: str
    function_pmids: list[str]
    n_human_partners: int
    n_viral_partners: int
    homodimer: bool


def proteins(backend: Backend, protein_ids: ProteinIds) -> Rows[ProteinCard]:
    """Everything about proteins but their interactions and GO: UniProt's
    name and function text with the publications it cites, the virus and
    family of a viral protein, how many human and viral partners it has, and
    whether it binds itself. `function` is long, and is where UniProt says
    what the protein does."""
    check_proteins(backend, protein_ids)
    return whole(
        [
            ProteinCard.model_validate(row)
            for row in backend.rows(
                f"""MATCH (p:Protein) WHERE p.id IN $ids
            WITH p
            OPTIONAL MATCH (p)-[:FUNCTION_CITES]->(b:Publication)
            WITH p, collect(b.pmid) AS function_pmids
            OPTIONAL MATCH (p)-[:INTERACTS_WITH]-(q:Protein)
            WITH p, function_pmids,
                 count(DISTINCT CASE WHEN q:Human AND q <> p THEN q END) AS n_human,
                 count(DISTINCT CASE WHEN q:Viral THEN q END) AS n_viral,
                 count(CASE WHEN q = p THEN 1 END) > 0 AS homodimer
            OPTIONAL MATCH (p)-[:IN_TAXON]->(t:Virus)
            OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
            RETURN p.id AS id, p.name AS name, p.description AS description,
                   {KIND.format("p")} AS kind, t.name AS virus, f.name AS family,
                   p.function AS function, function_pmids,
                   n_human AS n_human_partners, n_viral AS n_viral_partners,
                   homodimer""",
                ids=protein_ids,
            )
        ]
    )


class ViralProtein(ProteinRecord):
    n_human_targets: int


def viral_proteins(
    backend: Backend,
    family: Family = None,
    virus: Virus = None,
    min_publications: MinPublications = 1,
    min_methods: MinMethods = 1,
    combine: Combine = "and",
) -> Rows[ViralProtein]:
    """The viral proteins of a family or a virus, each with how many human
    proteins it targets at the evidence level. A viral protein is curated:
    one mature protein of one virus, pooled over every strain and accession
    it was observed on."""
    if family is None and virus is None:
        raise ValueError("give a family or a virus")
    level = evidence_level("e", min_publications, min_methods, combine)
    check_scope(backend, family, virus, None)
    return whole(
        [
            ViralProtein.model_validate(row)
            for row in backend.rows(
                f"""MATCH (v:Viral)-[:IN_TAXON]->(t:Virus)
            OPTIONAL MATCH (t)-[:PARENT]->(f:Family)
            WITH v, t, f WHERE {viral_scope(family, virus, None)}
            OPTIONAL MATCH (v)-[e:INTERACTS_WITH]-(h:Human)
            WHERE {level}
            RETURN v.id AS id, v.name AS name, v.description AS description,
                   'viral' AS kind, t.name AS virus, f.name AS family,
                   count(DISTINCT h) AS n_human_targets
            ORDER BY virus, n_human_targets DESC""",
                family=family,
                virus=virus,
                min_publications=min_publications,
                min_methods=min_methods,
            )
        ]
    )
