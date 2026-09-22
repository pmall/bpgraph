"""The only place a bpgraph identifier is constructed.

Two labels need a derived id because their natural key is several values at
once; every other label keys on a value that comes straight from the data. See
docs/schema.md section 3.
"""

from bpgraph.enums import ProteinKind


def protein_id(accession: str, start: int, stop: int, kind: ProteinKind) -> str:
    """Bare accession for human proteins, accession plus span for viral ones.

    Human ids stay free of coordinates so that a UniProt release revising a
    sequence updates `stop` in place and leaves every interaction referencing
    the protein untouched.
    """
    if kind is ProteinKind.HUMAN:
        return accession
    return f"{accession}:{start}-{stop}"


def interaction_id(id_a: str, id_b: str) -> str:
    """Join two protein ids already in slot order. See `Description.partners`."""
    return f"{id_a}|{id_b}"
