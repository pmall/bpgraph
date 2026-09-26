"""Pydantic models mirroring docs/schema.md.

Every model is frozen and rejects unknown fields, so a drifting export fails at
the boundary rather than halfway through a build. No field is optional: text
that is unknown is the empty string, exactly as the graph stores it.
"""

from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bpgraph.enums import (
    GoNamespace,
    GoRelation,
    InteractionKind,
    ProteinKind,
    Side,
)
from bpgraph.ids import annotation_id, interaction_id

PMID = r"^\d+$"
PSIMI = r"^MI:\d{4}$"
GO = r"^GO:\d{7}$"


class Record(BaseModel):
    """Base for every ingestion model: immutable, and rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ProteinRef(Record):
    """A protein's id, and whether it is human or viral.

    Everything that points at a protein — a topic, a description, a GO
    annotation — takes one of these. A full `Protein` is itself a `ProteinRef`
    and is accepted wherever one is declared, so a loader holding proteins can
    pass them straight through without converting. The id is built by
    `bpgraph.ids` and by nothing else.
    """

    id: str = Field(min_length=1)
    kind: ProteinKind


class Protein(ProteinRef):
    """What an interaction joins: a host gene product, one Swiss-Prot entry, or
    a curated viral protein — `HBx` of HBV — whichever strains and accessions
    it was seen on."""

    name: str = Field(min_length=1)
    description: str = ""
    function: str = ""


class FunctionCitation(Record):
    """A publication UniProt cites as evidence for a protein's function text."""

    protein: ProteinRef
    pmid: str = Field(pattern=PMID)


class Virus(Record):
    """A curated virus, from `curation/viruses.tsv`: `HBV`, `SARS-CoV-2`."""

    taxon_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    full_name: str = Field(min_length=1)


class Family(Record):
    """The NCBI family above a curated virus, by its scientific name."""

    taxon_id: int = Field(ge=1)
    name: str = Field(min_length=1)


class TaxonLink(Record):
    """A `:PARENT` edge, virus to family. Derived from the taxonomy."""

    child_taxon_id: int = Field(ge=1)
    parent_taxon_id: int = Field(ge=1)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if self.child_taxon_id == self.parent_taxon_id:
            raise ValueError(f"taxon {self.child_taxon_id} is its own parent")
        return self


class Membership(Record):
    """An `:IN_TAXON` edge: a viral protein and the curated virus it is of."""

    protein: ProteinRef
    taxon_id: int = Field(ge=1)


class Topic(Record):
    """A subject of study, e.g. `ferroptosis`, curated as a list of proteins."""

    name: str = Field(min_length=1)


class Involvement(Record):
    """One human protein in one topic, with whatever that topic records about
    it. Each topic has its own columns, so they are kept as text, verbatim."""

    protein: ProteinRef
    topic: str = Field(min_length=1)
    properties: Mapping[str, str] = {}


class Publication(Record):
    """PubMed's metadata. A pmid PubMed did not return keeps its pmid alone:
    empty text, and `year` 0."""

    pmid: str = Field(pattern=PMID)
    title: str = ""
    year: int = Field(ge=0)
    journal: str = ""
    abstract: str = ""
    authors: tuple[str, ...] = ()


class Method(Record):
    """A PSI-MI detection method, and its curated class of independent evidence."""

    psimi_id: str = Field(pattern=PSIMI)
    name: str = Field(min_length=1)
    method_class: str = Field(min_length=1)


class Peptide(Record):
    """A short subsequence sufficient for an interaction, keyed by its residues."""

    sequence: str = Field(pattern=r"^[A-Z]+$", min_length=1)

    @property
    def length(self) -> int:
        return len(self.sequence)


class ReportedPeptide(Record):
    """A peptide as one description reports it: residues, and which partner
    they come from. The other partner is the target."""

    peptide: Peptide
    source: ProteinRef


class Description(Record):
    """One observation: one pair, one paper, one method.

    It comes from IntAct, from our curation, or from both: an IntAct row our
    curation also recorded carries the curation's `stable_ids` beside its
    `intact_id`. `id` is the IntAct one where there is one, otherwise the one
    `stable_id`.

    Slot order is derived here rather than stored: the host partner is always
    side `a`, and two host partners order alphabetically by id.

    The two partners may be the same protein — a homodimer, which the source
    records like any other pair and the graph keeps as one interaction with
    both of its `:INVOLVES` edges pointing at the one node.
    """

    id: str = Field(min_length=1)
    intact_id: str = ""
    stable_ids: tuple[str, ...] = ()
    partner_1: ProteinRef
    partner_2: ProteinRef
    pmid: str = Field(pattern=PMID)
    psimi_id: str = Field(pattern=PSIMI)
    peptides: tuple[ReportedPeptide, ...] = ()

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if not self.intact_id and len(self.stable_ids) != 1:
            raise ValueError(
                f"{self.id}: a description outside IntAct has exactly one stable_id"
            )
        first, second = self.partner_1, self.partner_2
        if first.kind is ProteinKind.VIRAL and second.kind is ProteinKind.VIRAL:
            raise ValueError(f"{self.id}: virus-virus interactions are not modelled")
        partners = {first.id, second.id}
        for reported in self.peptides:
            if reported.source.id not in partners:
                raise ValueError(
                    f"{self.id}: peptide {reported.peptide.sequence} comes from "
                    f"{reported.source.id}, which is not a partner"
                )
        return self

    @property
    def partners(self) -> tuple[ProteinRef, ProteinRef]:
        """The two partners in slot order: side `a` first."""
        first, second = self.partner_1, self.partner_2
        if first.kind is second.kind:
            return (first, second) if first.id <= second.id else (second, first)
        return (first, second) if first.kind is ProteinKind.HUMAN else (second, first)

    @property
    def interaction_kind(self) -> InteractionKind:
        if self.partner_1.kind is self.partner_2.kind:
            return InteractionKind.HH
        return InteractionKind.VH

    @property
    def interaction_id(self) -> str:
        side_a, side_b = self.partners
        return interaction_id(side_a.id, side_b.id)

    def source_side(self, reported: ReportedPeptide) -> Side:
        """Which slot a reported peptide was derived from.

        A homodimer has one protein on both slots, so its peptides all come
        from side `a` — source and target are the same node, and the
        distinction the property exists to make does not arise.
        """
        side_a, _ = self.partners
        return Side.A if reported.source.id == side_a.id else Side.B


class GoTerm(Record):
    go_id: str = Field(pattern=GO)
    name: str = Field(min_length=1)
    namespace: GoNamespace
    obsolete: bool = False


class GoEdge(Record):
    """One edge of the GO ontology, child to parent."""

    child_go_id: str = Field(pattern=GO)
    parent_go_id: str = Field(pattern=GO)
    relation: GoRelation


class GoAnnotation(Record):
    """One experimental GO annotation of a host protein, and the one
    publication it cites — reified, as a description is."""

    protein: ProteinRef
    go_id: str = Field(pattern=GO)
    qualifier: str = ""
    evidence_code: str = Field(min_length=1)
    assigned_by: str = ""
    pmid: str = Field(pattern=PMID)

    @property
    def id(self) -> str:
        return annotation_id(
            self.protein.id,
            self.go_id,
            self.pmid,
            self.evidence_code,
            self.assigned_by,
            self.qualifier,
        )


class Snapshot(Record):
    """Everything one build writes to the graph.

    A loader's whole job is to produce one of these, from every silo of a run.
    """

    proteins: tuple[Protein, ...] = ()
    function_citations: tuple[FunctionCitation, ...] = ()
    viruses: tuple[Virus, ...] = ()
    families: tuple[Family, ...] = ()
    taxon_links: tuple[TaxonLink, ...] = ()
    memberships: tuple[Membership, ...] = ()
    topics: tuple[Topic, ...] = ()
    involvements: tuple[Involvement, ...] = ()
    publications: tuple[Publication, ...] = ()
    methods: tuple[Method, ...] = ()
    descriptions: tuple[Description, ...] = ()
    go_terms: tuple[GoTerm, ...] = ()
    go_edges: tuple[GoEdge, ...] = ()
    go_annotations: tuple[GoAnnotation, ...] = ()
