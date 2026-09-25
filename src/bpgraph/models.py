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
from bpgraph.ids import interaction_id

ACCESSION = r"^[A-Z0-9]+$"


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
    """What an interaction joins: a human gene product, or a curated viral
    protein — `HBx` of HBV — whichever strains and accessions it was seen on."""

    name: str = Field(min_length=1)
    description: str = ""
    function: str = ""


class Entry(Record):
    """A UniProt accession, and the strain it belongs to."""

    accession: str = Field(pattern=ACCESSION, min_length=6)
    taxon_id: int = Field(ge=1)
    taxon_name: str = Field(min_length=1)
    description: str = ""


class Location(Record):
    """An `:ON_ENTRY` edge: where one protein sits on one entry.

    A human protein is the whole chain of its one entry, so the writer drops
    the coordinates there; they are kept here because the function text is
    fetched by span either way.
    """

    protein: ProteinRef
    accession: str = Field(pattern=ACCESSION, min_length=6)
    start: int = Field(ge=1)
    stop: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered_coordinates(self) -> Self:
        if self.stop < self.start:
            raise ValueError(f"stop {self.stop} precedes start {self.start}")
        return self

    @property
    def length(self) -> int:
        return self.stop - self.start + 1


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
    pmid: str = Field(pattern=r"^\d+$")
    title: str = Field(min_length=1)
    year: int = Field(ge=1800)
    journal: str = ""
    abstract: str = ""
    authors: tuple[str, ...] = ()


class Method(Record):
    psimi_id: str = Field(pattern=r"^MI:\d{4}$")
    name: str = Field(min_length=1)


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


class Partner(Record):
    """One side of a description: the protein, and the entry it was seen on."""

    protein: ProteinRef
    accession: str = Field(pattern=ACCESSION, min_length=6)


class Description(Record):
    """One row of the description table: one pair, one paper, one method.

    Slot order is derived here rather than stored: the human partner is always
    side `a`, and two human partners order alphabetically by id.

    The two partners may be the same protein — a homodimer, which the source
    records like any other pair and the graph keeps as one interaction with
    both of its `:INVOLVES` edges pointing at the one node.
    """

    stable_id: str = Field(min_length=1)
    partner_1: Partner
    partner_2: Partner
    pmid: str = Field(pattern=r"^\d+$")
    psimi_id: str = Field(pattern=r"^MI:\d{4}$")
    peptides: tuple[ReportedPeptide, ...] = ()

    @model_validator(mode="after")
    def _coherent_pair(self) -> Self:
        first, second = self.partner_1.protein, self.partner_2.protein
        if first.kind is ProteinKind.VIRAL and second.kind is ProteinKind.VIRAL:
            raise ValueError(
                f"{self.stable_id}: virus-virus interactions are not modelled"
            )
        partners = {first.id, second.id}
        for reported in self.peptides:
            if reported.source.id not in partners:
                raise ValueError(
                    f"{self.stable_id}: peptide {reported.peptide.sequence} comes from "
                    f"{reported.source.id}, which is not a partner"
                )
        return self

    @property
    def partners(self) -> tuple[Partner, Partner]:
        """The two partners in slot order: side `a` first."""
        first, second = self.partner_1, self.partner_2
        if first.protein.kind is second.protein.kind:
            ordered = first.protein.id <= second.protein.id
            return (first, second) if ordered else (second, first)
        human_first = first.protein.kind is ProteinKind.HUMAN
        return (first, second) if human_first else (second, first)

    @property
    def interaction_kind(self) -> InteractionKind:
        if self.partner_1.protein.kind is self.partner_2.protein.kind:
            return InteractionKind.HH
        return InteractionKind.VH

    @property
    def interaction_id(self) -> str:
        side_a, side_b = self.partners
        return interaction_id(side_a.protein.id, side_b.protein.id)

    def source_side(self, reported: ReportedPeptide) -> Side:
        """Which slot a reported peptide was derived from.

        A homodimer has one protein on both slots, so its peptides all come
        from side `a` — source and target are the same node, and the
        distinction the property exists to make does not arise.
        """
        side_a, _ = self.partners
        return Side.A if reported.source.id == side_a.protein.id else Side.B


class GoTerm(Record):
    go_id: str = Field(pattern=r"^GO:\d{7}$")
    name: str = Field(min_length=1)
    namespace: GoNamespace
    obsolete: bool = False


class GoEdge(Record):
    """One edge of the GO ontology, child to parent."""

    child_go_id: str = Field(pattern=r"^GO:\d{7}$")
    parent_go_id: str = Field(pattern=r"^GO:\d{7}$")
    relation: GoRelation


class GoAnnotation(Record):
    protein: ProteinRef
    go_id: str = Field(pattern=r"^GO:\d{7}$")
    evidence_code: str = Field(min_length=1)
    assigned_by: str = ""
    qualifier: str = ""


class Export(Record):
    """One full snapshot of the relational database — everything a run writes.

    A loader's whole job is to produce one of these. Stages may be empty: a run
    that skips the GO fetch simply leaves the GO collections at their defaults.
    """

    proteins: tuple[Protein, ...] = ()
    entries: tuple[Entry, ...] = ()
    locations: tuple[Location, ...] = ()
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
