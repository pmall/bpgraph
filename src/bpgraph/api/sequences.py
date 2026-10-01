"""Sequences, from the vaults: one protein's residues at a time, to verify a
hypothesis the graph produced, never to reason over many."""

from typing import Annotated

from pydantic import Field

from bpgraph import vault
from bpgraph.api.base import Backend, Record, Rows, whole
from bpgraph.api.names import check_proteins
from bpgraph.run import HUMAN


class HumanSequence(Record):
    accession: str
    length: int
    sequence: str


def human_sequences(
    backend: Backend,
    accessions: Annotated[
        list[str],
        Field(min_length=1, description="Human accessions."),
    ],
) -> Rows[HumanSequence]:
    """The Swiss-Prot sequence of human proteins."""
    check_proteins(backend, accessions, "human")
    found = vault.host_sequences(backend.vault, HUMAN, accessions)
    return whole(
        [
            HumanSequence(accession=accession, length=len(sequence), sequence=sequence)
            for accession in accessions
            if (sequence := found.get(accession)) is not None
        ]
    )


class MatureSequence(Record):
    accession: str
    strain: str
    start: int
    stop: int
    length: int
    sequence: str


def viral_sequences(
    backend: Backend,
    protein_id: Annotated[
        str, Field(description="A viral protein id, e.g. `10407:HBx`.")
    ],
) -> Rows[MatureSequence]:
    """Every place a viral protein was observed: the UniProt entry, its
    strain, the span of the mature protein on it (1-based, inclusive) and the
    residues there. A viral protein pools strains and accessions, so it has
    as many sequences as places curation saw it; `evidence` says which entry
    each VH description observed."""
    check_proteins(backend, [protein_id], "viral")
    return whole(
        [
            MatureSequence(
                accession=site.accession,
                strain=site.taxon_name,
                start=site.start,
                stop=site.stop,
                length=len(site.sequence),
                sequence=site.sequence,
            )
            for site in vault.mature_sequences(backend.vault, protein_id)
        ]
    )
