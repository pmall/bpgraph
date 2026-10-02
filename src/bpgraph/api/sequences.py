"""What the vaults hold and the graph does not: sequences, and the viral
mature protein each VH description observed."""

from typing import Annotated

from pydantic import Field

from bpgraph import vault
from bpgraph.api.base import Backend, Record, Rows, whole
from bpgraph.api.names import (
    ViralKey,
    check_accessions,
    check_viral,
    resolve_stable_ids,
)
from bpgraph.run import HUMAN


class HumanSequence(Record):
    accession: str
    length: int
    sequence: str


def human_sequences(
    backend: Backend,
    accessions: Annotated[
        list[str],
        Field(min_length=1, description="UniProt accessions of human proteins."),
    ],
) -> Rows[HumanSequence]:
    """The Swiss-Prot sequence of human proteins."""
    check_accessions(backend, accessions)
    found = vault.host_sequences(backend.vault, HUMAN, accessions)
    return whole(
        [
            HumanSequence(accession=accession, length=len(sequence), sequence=sequence)
            for accession in accessions
            if (sequence := found.get(accession)) is not None
        ]
    )


class MatureSequence(Record):
    ncbi_taxon_id: int
    name: str
    accession: str
    strain: str
    start: int
    stop: int
    length: int
    sequence: str


def viral_sequences(
    backend: Backend,
    proteins: Annotated[
        list[ViralKey],
        Field(min_length=1, description="Viral proteins, by virus and name."),
    ],
) -> Rows[MatureSequence]:
    """Every place viral proteins were observed: for each, one row per
    UniProt entry curation saw it on, with the entry's strain, the span of the
    mature protein on it (1-based, inclusive) and the residues there. A viral
    protein pools strains and entries, so it has as many sequences as places
    curation saw it."""
    check_viral(backend, proteins)
    return whole(
        [
            MatureSequence(
                ncbi_taxon_id=key.ncbi_taxon_id,
                name=key.name,
                accession=site.accession,
                strain=site.taxon_name,
                start=site.start,
                stop=site.stop,
                length=len(site.sequence),
                sequence=site.sequence,
            )
            for key in dict.fromkeys(proteins)
            for site in vault.mature_sequences(
                backend.vault, key.ncbi_taxon_id, key.name
            )
        ]
    )


class ObservedSequence(Record):
    stable_id: str
    accession: str
    strain: str
    start: int
    stop: int
    length: int
    sequence: str


def observed_sequences(
    backend: Backend,
    stable_ids: Annotated[
        list[str],
        Field(
            min_length=1,
            description="The `stable_id` of curated VH descriptions.",
        ),
    ],
) -> Rows[ObservedSequence]:
    """The exact mature viral protein each VH description observed: the
    UniProt entry and strain the experiment used, which the graph's pooled
    viral protein does not say, the span of the protein on it (1-based,
    inclusive) and the residues there."""
    found = vault.observed_sequences(
        backend.vault, resolve_stable_ids(backend, stable_ids)
    )
    return whole(
        [
            ObservedSequence(
                stable_id=d,
                accession=site.accession,
                strain=site.taxon_name,
                start=site.start,
                stop=site.stop,
                length=len(site.sequence),
                sequence=site.sequence,
            )
            for d in dict.fromkeys(stable_ids)
            if (site := found.get(d)) is not None
        ]
    )
